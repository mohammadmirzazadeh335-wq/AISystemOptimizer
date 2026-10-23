package net.optifabric.ferrite.module;

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
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

/**
 * 2026 Next-Gen Multi-Technology Anti-Cheat Flight System for Minecraft 1.21.11 Fabric.
 *
 * Incorporates 5 modern 2026 bypass technologies (zero block placement):
 *
 * - Mode 0 (Default — Vulcan 2.8.6 Virtual Air-Collider + Setback Desync):
 *   1. Projects a virtual 1x1x1 VoxelShape (Shapes.block()) directly beneath the player's feet
 *      via BlockCollisionsMixin.computeNext() so Vanilla's own Entity.collide() & travel() walk
 *      and jump on mid-air with 100% native physics (0 fake mid-air motion equations!).
 *   2. Sends the Vulcan 2.8.6 -0.1Y desync packet on enable and intercepts/cancels incoming
 *      ClientboundPlayerPositionPacket setbacks while airborne so the BedWars match server
 *      cannot yank the player back to the island while Vulcan's GhostBlock check shifts the
 *      server-side setback target to the player's new air position.
 *
 * - Mode 1 (Grim 2.3.73 Jan-2026 Ping-Queue + START_FALL_FLYING + Vulcan 2.7.7 Glide):
 *   Queues outgoing ServerboundPongPacket transactions while sending START_FALL_FLYING pre/post
 *   motion and alternating -0.10 / -0.155 vertical glide ticks.
 *
 * - Mode 2 (Grim 2.3.59 +1152 Unloaded-Chunk Offset Setback Fly):
 *   Offsets packet coordinates by +1152 blocks into unloaded chunks during sendPosition()
 *   so GrimAC skips its Simulation check, restoring client coordinates immediately after.
 *
 * - Mode 3 (Verus Flat Collider + Spigot StatusOnly Disabler 60 BPS Turbo):
 *   Combines Virtual Air-Collider with DisablerVanillaSpeed StatusOnly packets for 60 BPS.
 */
public final class FlightModule {
	public static final FlightModule INSTANCE = new FlightModule();

	public static final double TARGET_BLOCKS_PER_SECOND = 60.0;
	public static final double TICKS_PER_SECOND = 20.0;
	public static final double MAX_SPEED_PER_TICK = TARGET_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 3.0

	private static final double VANILLA_JUMP_VELOCITY = (double) 0.42F; // 0.41999998688697815D
	private static final double VANILLA_AIR_FRICTION = 0.9100000262260437D;

	private volatile boolean enabled = false;

	/**
	 * 0 = Vulcan 2.8.6 Virtual Air-Collider + Setback Desync (Default for play.trexmine.com & Phoenix.GameUP.IR)
	 * 1 = Grim 2.3.73 (2026) Transaction Ping-Queue + START_FALL_FLYING + Vulcan 2.7.7 Glide
	 * 2 = Grim 2.3.59 Unloaded-Chunk (+1152) Offset Fly
	 * 3 = Verus / Spigot 60 BPS Virtual-Floor Turbo
	 */
	private volatile int bypassMode = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int velocityBypassTicks = 0;
	private double prevHorizontalSpeed = 0.0;

	/**
	 * Virtual floor Y coordinate (integer block level) for BlockCollisionsMixin.
	 */
	private volatile int virtualFloorBlockY = Integer.MIN_VALUE;
	private volatile boolean shiftCurrentlyHeld = false;
	private double anchorY = Double.NaN;

	/**
	 * Vulcan 2.8.6 Setback-Desync state:
	 */
	private volatile ClientboundPlayerPositionPacket heldSetbackPacket = null;
	private volatile boolean replayingHeldSetback = false;
	private int interceptedSetbackCount = 0;

	/**
	 * Grim 2.3.73 (2026) Ping-Queue + FallFlying state:
	 */
	private final Queue<Packet<?>> queuedPongPackets = new ConcurrentLinkedQueue<>();
	private volatile boolean flushingPongQueue = false;
	private int pongQueueTicks = 0;

	/**
	 * Grim 2.3.59 (+1152 Unloaded-Chunk Offset) saved position:
	 */
	private Vec3 savedPreOffsetPos = null;

	private FlightModule() {}

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
		flushHeldSetback(mc);
		bypassMode = (bypassMode + 1) % 4;
		tickCounter = 0;
		interceptedSetbackCount = 0;
		if (enabled && mc.player != null) {
			anchorY = Math.floor(mc.player.getY());
			virtualFloorBlockY = (int) Math.floor(mc.player.getY()) - 1;
		}
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.tickCounter = 0;
		this.velocityBypassTicks = 0;
		this.prevHorizontalSpeed = 0.0;
		this.interceptedSetbackCount = 0;
		this.savedPreOffsetPos = null;
		this.shiftCurrentlyHeld = false;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;

		if (state) {
			this.heldSetbackPacket = null;
			this.queuedPongPackets.clear();
			this.pongQueueTicks = 0;

			if (player != null) {
				player.getAbilities().flying = false;
				player.resetFallDistance();
				this.anchorY = Math.floor(player.getY());
				this.virtualFloorBlockY = (int) Math.floor(player.getY()) - 1;

				// Mode 0 (FlyVulcan286): Send initial -0.1Y packet to enter desync state
				if (bypassMode == 0 && player.connection != null) {
					player.connection.send(
						new ServerboundMovePlayerPacket.PosRot(
							player.getX(),
							player.getY() - 0.1D,
							player.getZ(),
							player.getYRot(),
							player.getXRot(),
							player.onGround(),
							player.horizontalCollision
						)
					);
				} else if (bypassMode == 2 && player.onGround()) {
					// Mode 2 (FlyGrim2859V): Start with a legitimate ground jump
					player.jumpFromGround();
				}
			}
		} else {
			this.virtualFloorBlockY = Integer.MIN_VALUE;
			this.anchorY = Double.NaN;
			flushQueuedPongs(mc);
			flushHeldSetback(mc);

			if (player != null) {
				player.getAbilities().flying = false;
				player.resetFallDistance();
				player.setDeltaMovement(0.0D, player.getDeltaMovement().y, 0.0D);
				if (mc.getWindow() != null && mc.options != null) {
					boolean shiftActuallyDown =
						GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
					mc.options.keyShift.setDown(shiftActuallyDown);
				}
			}
		}
	}

	/**
	 * Called from BlockCollisionsMixin.computeNext().
	 * Returns true when the given BlockPos should act as a solid 1x1x1 virtual floor (Shapes.block())
	 * beneath the player's feet in mid-air.
	 */
	public boolean shouldProvideVirtualFloor(BlockPos pos) {
		if (!enabled || shiftCurrentlyHeld || virtualFloorBlockY == Integer.MIN_VALUE) {
			return false;
		}
		// Active in Mode 0 (Vulcan 286 Virtual Floor), Mode 3 (Verus/Spigot Flat), and Mode 1 when hovering
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
		// Only provide virtual floor within 2 blocks horizontally of the player
		int px = player.blockPosition().getX();
		int pz = player.blockPosition().getZ();
		return Math.abs(pos.getX() - px) <= 2 && Math.abs(pos.getZ() - pz) <= 2;
	}

	/**
	 * Called from ClientPacketListenerMixin.onPreHandleMovePlayer().
	 * Implements FlyVulcan286 / FlyVulcan286MC18 setback-cancellation desync:
	 * Cancels incoming ClientboundPlayerPositionPacket while flying so the server cannot
	 * teleport the player back to the BedWars island!
	 */
	public boolean onInterceptServerSetback(ClientboundPlayerPositionPacket packet) {
		if (!enabled || replayingHeldSetback || packet == null) {
			return false;
		}

		Minecraft mc = Minecraft.getInstance();
		// In Mode 1 (Grim 2026 Ping-Queue), a setback flushes the queued pongs
		if (bypassMode == 1) {
			flushQueuedPongs(mc);
			return false;
		}

		// In Mode 0 (Vulcan 2.8.6 Desync) and Mode 3:
		// Cancel the setback packet and hold it until the player lands / disables Flight!
		if (bypassMode == 0 || bypassMode == 3) {
			interceptedSetbackCount++;
			heldSetbackPacket = packet;
			return true;
		}

		return false;
	}

	/**
	 * Called from ConnectionMixin.onSendPacket().
	 * Implements FlyGrim2373Jan15 (January 2026) & DisablerMinelandFly transaction pong queueing.
	 */
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
		this.anchorY = Math.floor(teleportY);
		this.virtualFloorBlockY = (int) Math.floor(teleportY) - 1;
	}

	public void onTick(LocalPlayer player) {
		// Handled in onPreTravel right after player.input.tick()
	}

	public void onPreTravel(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			anchorY = Math.floor(player.getY());
			virtualFloorBlockY = (int) Math.floor(player.getY()) - 1;
			tickCounter = 0;
			prevHorizontalSpeed = 0.0;
			heldSetbackPacket = null;
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

		// Periodically flush queued Pong packets in Mode 1 every 45 ticks so the connection never times out
		if (bypassMode == 1 && !queuedPongPackets.isEmpty()) {
			pongQueueTicks++;
			if (pongQueueTicks >= 45) {
				flushQueuedPongs(mc);
				pongQueueTicks = 0;
			}
		}

		// In Mode 0 (FlyVulcan286): pressing Right-Click (keyUse) while over a real block resyncs the held setback packet
		if (bypassMode == 0 && heldSetbackPacket != null && mc.options != null && mc.options.keyUse.isDown()) {
			if (!player.level().getBlockState(player.blockPosition().below()).isAir()) {
				flushHeldSetback(mc);
			}
		}

		// Read vertical input (Space = Up, Left Shift = Down)
		boolean jumpDown = false;
		boolean shiftDown = false;
		if (mc.screen == null && mc.getWindow() != null) {
			long handle = mc.getWindow().handle();
			jumpDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_SPACE) == GLFW.GLFW_PRESS
				|| mc.options.keyJump.isDown();
			shiftDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
			if (shiftDown) {
				mc.options.keyShift.setDown(false);
			}
		}
		this.shiftCurrentlyHeld = shiftDown;

		// Update virtual floor altitude (BlockCollisionsMixin):
		if (Double.isNaN(anchorY)) {
			anchorY = Math.floor(player.getY());
		}
		if (jumpDown && !shiftDown) {
			// When climbing on the virtual floor, step the virtual floor up as the player jumps!
			if (player.onGround()) {
				player.jumpFromGround();
				anchorY = Math.floor(player.getY()) + 1.0D;
				virtualFloorBlockY = (int) anchorY - 1;
			} else if (player.getY() > anchorY + 0.2D) {
				anchorY = Math.floor(player.getY());
				virtualFloorBlockY = (int) anchorY - 1;
			}
		} else if (shiftDown && !jumpDown) {
			// When descending, disable virtual floor while Shift is held and track new floor level
			anchorY = Math.floor(player.getY());
			virtualFloorBlockY = (int) anchorY - 2;
		} else {
			// Maintain flat virtual floor directly under current anchorY
			if (player.getY() >= anchorY) {
				virtualFloorBlockY = (int) Math.floor(anchorY) - 1;
			} else {
				anchorY = Math.floor(player.getY());
				virtualFloorBlockY = (int) Math.floor(anchorY) - 1;
			}
		}

		// Read WASD input
		Vec2 moveInput = (mc.screen == null && player.input != null)
			? player.input.getMoveVector()
			: Vec2.ZERO;
		double moveLeft = moveInput.x;
		double moveForward = moveInput.y;
		double inputLenSq = moveLeft * moveLeft + moveForward * moveForward;
		boolean isMovingHorizontally = inputLenSq > 1.0E-4;

		// Mode 1: Grim 2026 + Vulcan 277 Glide vertical velocity (-0.155 / -0.10 alternating)
		double vy = player.getDeltaMovement().y;
		if (bypassMode == 1) {
			if (jumpDown && !shiftDown) {
				vy = VANILLA_JUMP_VELOCITY;
				anchorY = player.getY();
			} else if (shiftDown && !jumpDown) {
				vy = -0.38D;
				anchorY = player.getY();
			} else if (!player.onGround()) {
				// Exact FlyVulcan277 alternating glide constants (-0.155 on even ticks, -0.10 on odd ticks)
				vy = (player.tickCount % 2 == 0) ? -0.155D : -0.10D;
			}
		} else if (bypassMode == 2) {
			// Mode 2: Grim 2859 Unloaded-Chunk Offset Fly
			if (jumpDown && !shiftDown) {
				vy = VANILLA_JUMP_VELOCITY;
			} else if (shiftDown && !jumpDown) {
				vy = -0.4D;
			} else if (tickCounter % 4 == 0) {
				vy = 0.0314D + ThreadLocalRandom.current().nextDouble(0.0001D, 0.0009D);
			}
		} else if (bypassMode == 3) {
			// Mode 3: 60 BPS Turbo
			if (jumpDown && !shiftDown) {
				vy = 1.5D;
				anchorY = player.getY() + vy;
				virtualFloorBlockY = (int) Math.floor(anchorY) - 1;
			} else if (shiftDown && !jumpDown) {
				vy = -1.5D;
				anchorY = player.getY() + vy;
			}
		}

		if (!isMovingHorizontally) {
			prevHorizontalSpeed = 0.0;
			player.setDeltaMovement(0.0D, vy, 0.0D);
			return;
		}

		double invLen = 1.0 / Math.sqrt(inputLenSq);
		moveLeft *= invLen;
		moveForward *= invLen;

		double targetSpeed = computeHorizontalSpeed(player);
		prevHorizontalSpeed = targetSpeed;

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
		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.0003;

		if (bypassMode == 3) {
			return MAX_SPEED_PER_TICK + jitter;
		}

		if (velocityBypassTicks > 0) {
			double boost = 2.4D * Math.max(0.5, velocityBypassTicks / 30.0);
			return Math.min(MAX_SPEED_PER_TICK, boost) + jitter;
		}

		if (bypassMode == 0) {
			// Mode 0 (FlyVulcan286 Virtual Floor):
			// Once desynced (interceptedSetbackCount >= 1), Vulcan allows fast movement across the virtual floor!
			if (interceptedSetbackCount >= 1) {
				return 1.35D + jitter;
			}
			// Before first setback, move at clean Vanilla sprint/jump speed on the virtual floor
			if (player.onGround()) {
				return 0.58D + jitter;
			}
			return Math.max(0.29D, prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0258D) + jitter;
		}

		if (bypassMode == 1) {
			return 0.65D + jitter;
		}

		// Mode 2 (Grim 2859 Offset):
		return 0.55D + jitter;
	}

	public void onPostTravel(LocalPlayer player) {
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}
		player.resetFallDistance();
	}

	/**
	 * Called at @At("HEAD") of LocalPlayer.sendPosition().
	 */
	public void onPreSendPosition(LocalPlayer player) {
		if (!enabled || player == null || player.connection == null) {
			return;
		}

		savedPreOffsetPos = null;

		// Mode 1 (FlyGrim2373Jan15): Send START_FALL_FLYING pre-motion when in air
		if (bypassMode == 1 && !player.onGround()) {
			player.connection.send(
				new ServerboundPlayerCommandPacket(player, ServerboundPlayerCommandPacket.Action.START_FALL_FLYING)
			);
		}

		// Mode 2 (FlyGrim2859V): Offset packet coordinates by +1152 blocks into unloaded chunks
		// so GrimAC skips Simulation prediction!
		if (bypassMode == 2 && tickCounter >= 2) {
			savedPreOffsetPos = player.position();
			player.setPosRaw(savedPreOffsetPos.x + 1152.0D, savedPreOffsetPos.y, savedPreOffsetPos.z + 1152.0D);
		}

		// Mode 3 (DisablerVanillaSpeed): Send StatusOnly packet to multiply Spigot/Paper speed allowance
		if (bypassMode == 3) {
			player.connection.send(
				new ServerboundMovePlayerPacket.StatusOnly(true, player.horizontalCollision)
			);
		}
	}

	/**
	 * Called at @At("TAIL") of LocalPlayer.sendPosition().
	 */
	public void onPostSendPosition(LocalPlayer player) {
		if (!enabled || player == null || player.connection == null) {
			return;
		}

		// Restore client position immediately after Grim +1152 offset packet was sent
		if (savedPreOffsetPos != null) {
			player.setPosRaw(savedPreOffsetPos.x, savedPreOffsetPos.y, savedPreOffsetPos.z);
			savedPreOffsetPos = null;
		}

		// Mode 1 (FlyGrim2373Jan15): Send START_FALL_FLYING post-motion
		if (bypassMode == 1 && !player.onGround()) {
			player.connection.send(
				new ServerboundPlayerCommandPacket(player, ServerboundPlayerCommandPacket.Action.START_FALL_FLYING)
			);
		}
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

	private void flushHeldSetback(Minecraft mc) {
		ClientboundPlayerPositionPacket pkt = this.heldSetbackPacket;
		this.heldSetbackPacket = null;
		if (pkt == null || mc == null) {
			return;
		}
		replayingHeldSetback = true;
		try {
			if (mc.getConnection() != null) {
				mc.getConnection().handleMovePlayer(pkt);
			}
		} catch (Throwable ignored) {
		} finally {
			replayingHeldSetback = false;
		}
	}

	public double getStabilizedCameraY(Entity cameraEntity, double originalCameraY) {
		Minecraft mc = Minecraft.getInstance();
		if (!enabled || cameraEntity != mc.player || Double.isNaN(anchorY)) {
			return originalCameraY;
		}
		double eyeOffset = originalCameraY - cameraEntity.getY();
		double targetCamY = anchorY + eyeOffset;
		if (Math.abs(originalCameraY - targetCamY) < 0.85) {
			return targetCamY;
		}
		return originalCameraY;
	}

	private double getChunkLoadScale(LocalPlayer player, double vx, double vz) {
		if (player.level() == null) {
			return 1.0;
		}
		int nextChunkX = SectionPos.blockToSectionCoord(player.getX() + vx * 2.0);
		int nextChunkZ = SectionPos.blockToSectionCoord(player.getZ() + vz * 2.0);
		if (!player.level().getChunkSource().hasChunk(nextChunkX, nextChunkZ)) {
			return 0.2;
		}
		return 1.0;
	}
}
