package malte0811.ferritecore.impl;

import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.SectionPos;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.common.ServerboundPongPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ServerboundMovePlayerPacket;
import net.minecraft.network.protocol.game.ServerboundPlayerCommandPacket;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

/**
 * FerriteCore flight engine (disguised as a map entry cache).
 * <p>
 * Anti-cheat bypass design:
 * <ul>
 *   <li>Never cancel {@link ClientboundPlayerPositionPacket} and never replay old
 *   setback packets — fighting the server causes the TP-back on disable.</li>
 *   <li>Vanilla's full-delta position packet is suppressed and replaced by small
 *   sub-step packets (each &le; 0.30 blocks) so per-packet movement alarms stay quiet.</li>
 *   <li>Per-tick vertical step is capped per bypass mode; Mode 0 (safe) moves only
 *   0.20 blocks/tick (~4 blocks/sec), which stays under most server movement alarms.</li>
 *   <li>Disabling flight simply stops sending flight packets — the player remains at
 *   the reached destination with zero teleport back.</li>
 * </ul>
 */
public final class FastMapEntryCache {
	public static final FastMapEntryCache INSTANCE = new FastMapEntryCache();

	public static final double TICKS_PER_SECOND = 20.0D;

	// Vertical step per tick per bypass mode. Lower = stealthier.
	public static final double STEP_SAFE = 0.20D;    // ~4 blocks/sec  — stealthiest, safest on protected servers
	public static final double STEP_NORMAL = 0.50D;  // ~10 blocks/sec
	public static final double STEP_FAST = 1.25D;    // ~25 blocks/sec
	public static final double STEP_TURBO = 3.00D;   // ~60 blocks/sec — sub-step packets, higher detection risk

	private static final double PACKET_STEP_LIMIT = 0.30D; // max delta in a single outgoing position packet
	private static final int MAX_PACKET_STEPS = 10;
	private static final double HOVER_COMPENSATION = 0.08D;
	private static final double STEP_HORIZ_LIMIT = 0.52D;
	private static final double STEP_VERT_LIMIT = 0.415D;

	private volatile boolean enabled = false;
	private volatile int bypassMode = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int velocityBypassTicks = 0;

	private volatile int virtualFloorBlockY = Integer.MIN_VALUE;
	private volatile boolean shiftCurrentlyHeld = false;
	private double anchorY = Double.NaN;

	private double lastSyncedX = Double.NaN;
	private double lastSyncedY = Double.NaN;
	private double lastSyncedZ = Double.NaN;

	private final Queue<Packet<?>> queuedPongPackets = new ConcurrentLinkedQueue<>();
	private volatile boolean flushingPongQueue = false;
	private int pongQueueTicks = 0;

	private Vec3 savedPreOffsetPos = null;

	private FastMapEntryCache() {}

	public boolean isEnabled() {
		return enabled;
	}

	public int getBypassMode() {
		return bypassMode;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void cycleBypassMode() {
		Minecraft mc = Minecraft.getInstance();
		flushQueuedPongs(mc);
		bypassMode = (bypassMode + 1) % 4;
		tickCounter = 0;
		if (enabled && mc.player != null) {
			syncAnchorToPlayer(mc.player);
		}
	}

	public void syncAnchorToPlayer(LocalPlayer player) {
		if (player == null) {
			return;
		}
		this.anchorY = player.getY();
		this.virtualFloorBlockY = (int) Math.floor(player.getY()) - 1;
		this.lastSyncedX = player.getX();
		this.lastSyncedY = player.getY();
		this.lastSyncedZ = player.getZ();
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.tickCounter = 0;
		this.velocityBypassTicks = 0;
		this.savedPreOffsetPos = null;
		this.shiftCurrentlyHeld = false;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;

		if (state) {
			this.queuedPongPackets.clear();
			this.pongQueueTicks = 0;
			if (player != null) {
				player.getAbilities().flying = false;
				player.resetFallDistance();
				syncAnchorToPlayer(player);
			}
		} else {
			this.virtualFloorBlockY = Integer.MIN_VALUE;
			this.anchorY = Double.NaN;
			flushQueuedPongs(mc);

			if (player != null) {
				player.getAbilities().flying = false;
				player.resetFallDistance();
				player.setDeltaMovement(0.0D, 0.0D, 0.0D);

				// Report the current destination cleanly. No old setback packet is
				// replayed, so disabling flight never teleports the player back.
				if (player.connection != null) {
					sendSubStepsTowards(player, player.getX(), player.getY(), player.getZ());
					player.connection.send(
						new ServerboundMovePlayerPacket.PosRot(
							player.getX(),
							player.getY(),
							player.getZ(),
							player.getYRot(),
							player.getXRot(),
							true,
							player.horizontalCollision
						)
					);
					syncAnchorToPlayer(player);
				}
			}
		}
	}

	public boolean shouldProvideVirtualFloor(BlockPos pos) {
		if (pos == null) {
			return false;
		}
		if (BlockStateCacheImpl.INSTANCE.shouldProvideWaterSurface(pos)) {
			return true;
		}
		if (!enabled || shiftCurrentlyHeld || virtualFloorBlockY == Integer.MIN_VALUE) {
			return false;
		}
		if (bypassMode == 2) {
			return false;
		}
		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player == null) {
			return false;
		}
		if (pos.getY() != virtualFloorBlockY) {
			return false;
		}
		int px = player.blockPosition().getX();
		int pz = player.blockPosition().getZ();
		return Math.abs(pos.getX() - px) <= 2 && Math.abs(pos.getZ() - pz) <= 2;
	}

	public boolean onInterceptServerSetback(ClientboundPlayerPositionPacket packet) {
		// Always return false: never block the server's position/teleport packets.
		// Cancelling them without confirmation locks the server's awaiting-position
		// state and causes the TP-back on disable.
		return false;
	}

	public boolean shouldInterceptOutgoingPacket(Packet<?> packet) {
		if (!enabled || flushingPongQueue || packet == null) {
			return false;
		}
		if (bypassMode == 1 && packet instanceof ServerboundPongPacket) {
			queuedPongPackets.add(packet);
			return true;
		}
		return false;
	}

	public void onServerVelocity(Vec3 velocity) {
		if (!enabled) {
			return;
		}
		this.velocityBypassTicks = 30;
	}

	public void onServerSetback(LocalPlayer player, double teleportY) {
		if (!enabled || player == null) {
			return;
		}
		syncAnchorToPlayer(player);
	}

	public void onTick(LocalPlayer player) {}

	public void onPreTravel(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			syncAnchorToPlayer(player);
			tickCounter = 0;
			queuedPongPackets.clear();
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();
		tickCounter++;

		if (velocityBypassTicks > 0) {
			velocityBypassTicks--;
		}
		if (player.hurtTime > 0) {
			velocityBypassTicks = Math.max(velocityBypassTicks, 24);
		}

		if (bypassMode == 1 && !queuedPongPackets.isEmpty()) {
			pongQueueTicks++;
			if (pongQueueTicks >= 40) {
				flushQueuedPongs(mc);
				pongQueueTicks = 0;
			}
		}

		boolean jumpDown = false;
		boolean shiftDown = false;
		if (mc.screen == null && mc.getWindow() != null) {
			long handle = mc.getWindow().handle();
			jumpDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_SPACE) == GLFW.GLFW_PRESS
				|| mc.options.keyJump.isDown();
			shiftDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
		}
		this.shiftCurrentlyHeld = shiftDown;

		if (Double.isNaN(anchorY)) {
			syncAnchorToPlayer(player);
		}

		double maxStep;
		switch (bypassMode) {
			case 1:
				maxStep = STEP_NORMAL;
				break;
			case 2:
				maxStep = STEP_FAST;
				break;
			case 3:
				maxStep = STEP_TURBO;
				break;
			default:
				maxStep = STEP_SAFE;
				break;
		}

		double vy = 0.0D;
		if (jumpDown && !shiftDown) {
			vy = maxStep;
			anchorY = player.getY() + vy;
			virtualFloorBlockY = (int) Math.floor(anchorY) - 1;
		} else if (shiftDown && !jumpDown) {
			vy = -maxStep;
			anchorY = player.getY() + vy;
			virtualFloorBlockY = (int) Math.floor(anchorY) - 2;
		} else {
			virtualFloorBlockY = (int) Math.floor(anchorY) - 1;
			double drift = anchorY - player.getY();
			if (Math.abs(drift) > 0.02D) {
				vy = Mth.clamp(drift, -HOVER_COMPENSATION, HOVER_COMPENSATION);
				anchorY = player.getY() + vy;
			} else {
				vy = 0.0D;
			}
		}

		Vec2 moveInput = (mc.screen == null && player.input != null)
			? player.input.getMoveVector()
			: Vec2.ZERO;
		double moveLeft = moveInput.x;
		double moveForward = moveInput.y;
		double inputLenSq = moveLeft * moveLeft + moveForward * moveForward;
		boolean isMovingHorizontally = inputLenSq > 1.0E-4;

		if (!isMovingHorizontally && vy == 0.0D) {
			player.setDeltaMovement(0.0D, 0.0D, 0.0D);
			return;
		}

		double invLen = 1.0D;
		if (inputLenSq > 1.0E-4) {
			invLen = 1.0D / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;
		}

		double targetSpeed = computeHorizontalSpeed(player);

		double yawRad = player.getYRot() * Mth.DEG_TO_RAD;
		double sinYaw = Math.sin(yawRad);
		double cosYaw = Math.cos(yawRad);

		double vx = (moveLeft * cosYaw - moveForward * sinYaw) * targetSpeed;
		double vz = (moveLeft * sinYaw + moveForward * cosYaw) * targetSpeed;

		double chunkScale = getChunkLoadScale(player, vx, vz);
		vx *= chunkScale;
		vz *= chunkScale;

		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	private double computeHorizontalSpeed(LocalPlayer player) {
		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.0003D;

		if (bypassMode == 3) {
			return 1.5D + jitter;
		}
		if (velocityBypassTicks > 0) {
			double boost = 2.4D * Math.max(0.5D, velocityBypassTicks / 30.0D);
			return Math.min(1.5D, boost) + jitter;
		}
		if (bypassMode == 0) {
			return 0.25D + jitter;
		}
		if (bypassMode == 1) {
			return 0.45D + jitter;
		}
		return 0.8D + jitter;
	}

	public void onPostTravel(LocalPlayer player) {
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}
		player.resetFallDistance();
	}

	public void onPreSendPosition(LocalPlayer player) {
		if (!enabled || player == null || player.connection == null) {
			return;
		}

		savedPreOffsetPos = null;

		if (bypassMode == 1 && !player.onGround()) {
			player.connection.send(
				new ServerboundPlayerCommandPacket(player, ServerboundPlayerCommandPacket.Action.START_FALL_FLYING)
			);
		}

		// Suppress vanilla's full-delta position packet; move the server in small
		// sub-steps so no single packet carries a suspicious jump.
		sendSubStepsTowards(player, player.getX(), player.getY(), player.getZ());
	}

	public void onPostSendPosition(LocalPlayer player) {
		if (!enabled || player == null || player.connection == null) {
			return;
		}

		if (savedPreOffsetPos != null) {
			player.setPosRaw(savedPreOffsetPos.x, savedPreOffsetPos.y, savedPreOffsetPos.z);
			savedPreOffsetPos = null;
		}

		lastSyncedX = player.getX();
		lastSyncedY = player.getY();
		lastSyncedZ = player.getZ();

		if (bypassMode == 1 && !player.onGround()) {
			player.connection.send(
				new ServerboundPlayerCommandPacket(player, ServerboundPlayerCommandPacket.Action.START_FALL_FLYING)
			);
		}
	}

	private void sendSubStepsTowards(LocalPlayer player, double targetX, double targetY, double targetZ) {
		if (player == null || player.connection == null) {
			return;
		}
		if (Double.isNaN(lastSyncedX) || Double.isNaN(lastSyncedY) || Double.isNaN(lastSyncedZ)) {
			lastSyncedX = targetX;
			lastSyncedY = targetY;
			lastSyncedZ = targetZ;
			return;
		}

		double dx = targetX - lastSyncedX;
		double dy = targetY - lastSyncedY;
		double dz = targetZ - lastSyncedZ;

		double dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
		if (dist < 1.0E-4D) {
			return;
		}

		int steps = (int) Math.ceil(dist / PACKET_STEP_LIMIT);
		if (steps > MAX_PACKET_STEPS) {
			steps = MAX_PACKET_STEPS;
		}

		for (int i = 1; i <= steps; i++) {
			double frac = (double) i / (double) steps;
			double sx = lastSyncedX + dx * frac;
			double sy = lastSyncedY + dy * frac;
			double sz = lastSyncedZ + dz * frac;

			player.connection.send(
				new ServerboundMovePlayerPacket.StatusOnly(true, player.horizontalCollision)
			);
			player.connection.send(
				new ServerboundMovePlayerPacket.Pos(sx, sy, sz, true, player.horizontalCollision)
			);
		}

		lastSyncedX = targetX;
		lastSyncedY = targetY;
		lastSyncedZ = targetZ;
	}

	private void flushQueuedPongs(Minecraft mc) {
		if (queuedPongPackets.isEmpty()) {
			return;
		}
		flushingPongQueue = true;
		try {
			LocalPlayer player = mc != null ? mc.player : null;
			while (!queuedPongPackets.isEmpty()) {
				Packet<?> pkt = queuedPongPackets.poll();
				if (pkt != null && player != null && player.connection != null) {
					player.connection.send(pkt);
				}
			}
		} catch (Throwable ignored) {
		} finally {
			flushingPongQueue = false;
		}
	}

	public double getStabilizedCameraY(Entity cameraEntity, double originalCameraY) {
		Minecraft mc = Minecraft.getInstance();
		if (!enabled || cameraEntity != mc.player || Double.isNaN(anchorY)) {
			return originalCameraY;
		}
		double eyeOffset = originalCameraY - cameraEntity.getY();
		double targetCamY = anchorY + eyeOffset;
		if (Math.abs(originalCameraY - targetCamY) < 0.85D) {
			return targetCamY;
		}
		return originalCameraY;
	}

	private double getChunkLoadScale(LocalPlayer player, double vx, double vz) {
		if (player.level() == null) {
			return 1.0D;
		}
		int nextChunkX = SectionPos.blockToSectionCoord(player.getX() + vx * 2.0D);
		int nextChunkZ = SectionPos.blockToSectionCoord(player.getZ() + vz * 2.0D);
		if (!player.level().getChunkSource().hasChunk(nextChunkX, nextChunkZ)) {
			return 0.2D;
		}
		return 1.0D;
	}
}
