package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.SectionPos;
import net.minecraft.util.Mth;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

public final class FlightModule {
	public static final FlightModule INSTANCE = new FlightModule();

	/**
	 * Target speed: 60.0 blocks per second.
	 * At 20 ticks per second (TPS): 60.0 / 20.0 = 3.0 blocks per tick.
	 */
	public static final double DEFAULT_BLOCKS_PER_SECOND = 60.0;
	public static final double STRICT_BLOCKS_PER_SECOND = 40.0;
	public static final double TURBO_BLOCKS_PER_SECOND = 80.0;
	public static final double TICKS_PER_SECOND = 20.0;

	/**
	 * Irrational golden-ratio conjugate dip base to bypass GCD (Greatest Common Divisor)
	 * mathematical anti-cheat checks on vertical packet deltas.
	 */
	private static final double IRRATIONAL_DIP_BASE = 0.03618033988749895;

	private volatile boolean enabled = false;
	/**
	 * 0 = 60 Blocks/s Lag-Free Stealth (Default)
	 * 1 = 40 Blocks/s Strict Anti-Cheat Bypass
	 * 2 = 80 Blocks/s Turbo Mode
	 */
	private volatile int speedPreset = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int moveRampTicks = 0;
	private int nextAntiKickTick = 36;

	private boolean savedRealOnGround = false;
	private boolean spoofingPacketState = false;
	private double savedX = 0.0;
	private double savedY = 0.0;
	private double savedZ = 0.0;

	private FlightModule() {}

	public boolean isEnabled() {
		return enabled;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void cycleBypassMode() {
		speedPreset = (speedPreset + 1) % 3;
	}

	public double getTargetBlocksPerTick() {
		return switch (speedPreset) {
			case 1 -> STRICT_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 2.0 (40 BPS)
			case 2 -> TURBO_BLOCKS_PER_SECOND / TICKS_PER_SECOND;  // 4.0 (80 BPS)
			default -> DEFAULT_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 3.0 (60 BPS)
		};
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.tickCounter = 0;
		this.moveRampTicks = 0;
		this.nextAntiKickTick = randomInterval();
		this.spoofingPacketState = false;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player != null) {
			player.getAbilities().flying = false;
			player.resetFallDistance();
			if (!state) {
				// Immediately zero velocity on pressing V again so player stops without lag or slide
				player.setDeltaMovement(Vec3.ZERO);
				if (mc.getWindow() != null && mc.options != null) {
					boolean shiftActuallyDown =
						GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
					mc.options.keyShift.setDown(shiftActuallyDown);
				}
			}
		}
	}

	public void onTick(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		// Reset state cleanly across dimension switches, respawns, or server reconnects
		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			tickCounter = 0;
			moveRampTicks = 0;
			spoofingPacketState = false;
			player.setDeltaMovement(Vec3.ZERO);
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();
		tickCounter++;

		double baseSpeedPerTick = getTargetBlocksPerTick(); // 3.0 blocks/tick = 60 blocks/sec

		// 1. Read WASD input and normalize so diagonal speed is also exactly 60 blocks/sec
		Vec2 moveInput = (mc.screen == null && player.input != null)
			? player.input.getMoveVector()
			: Vec2.ZERO;

		double moveLeft = moveInput.x;
		double moveForward = moveInput.y;
		double inputLenSq = moveLeft * moveLeft + moveForward * moveForward;

		double vx = 0.0;
		double vz = 0.0;

		if (inputLenSq > 1.0E-4) {
			moveRampTicks = Math.min(moveRampTicks + 1, 3);
			// Smooth 3-tick acceleration ramp prevents "moved wrongly!" server setback rubberbanding
			double rampMultiplier = switch (moveRampTicks) {
				case 1 -> 0.48;
				case 2 -> 0.80;
				default -> 1.0;
			};

			double invLen = 1.0 / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;

			// Non-repeating Gaussian micro-jitter (±0.0018) to bypass zero-variance speed checks
			double gaussianJitter = ThreadLocalRandom.current().nextGaussian() * 0.0008;
			double speed = (baseSpeedPerTick * rampMultiplier) + Mth.clamp(gaussianJitter, -0.0022, 0.0022);

			double yawRad = player.getYRot() * Mth.DEG_TO_RAD;
			double sinYaw = Math.sin(yawRad);
			double cosYaw = Math.cos(yawRad);

			vx = (moveLeft * cosYaw - moveForward * sinYaw) * speed;
			vz = (moveLeft * sinYaw + moveForward * cosYaw) * speed;
		} else {
			moveRampTicks = 0;
		}

		// 2. Vertical movement (Space = Up, Left Shift = Down)
		double verticalSpeedPerTick = Math.min(baseSpeedPerTick, 3.0);
		double vy = 0.0;

		if (mc.screen == null && mc.getWindow() != null) {
			long handle = mc.getWindow().handle();
			boolean jumpDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_SPACE) == GLFW.GLFW_PRESS
				|| mc.options.keyJump.isDown();
			boolean shiftDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;

			if (jumpDown) {
				double vJitter = ThreadLocalRandom.current().nextGaussian() * 0.0007;
				vy += verticalSpeedPerTick + Mth.clamp(vJitter, -0.002, 0.002);
			}
			if (shiftDown) {
				// Prevent sneak slowdown/pose packets while descending
				mc.options.keyShift.setDown(false);
				double vJitter = ThreadLocalRandom.current().nextGaussian() * 0.0007;
				vy -= verticalSpeedPerTick + Mth.clamp(vJitter, -0.002, 0.002);
			}
		}

		// 3. Normalize 3D diagonal velocity when ascending/descending + moving horizontally
		// so total 3D speed never exceeds 60 blocks/sec and never triggers Paper/Spigot setback lag
		if ((vx != 0.0 || vz != 0.0) && vy != 0.0) {
			double totalSpeedSq = vx * vx + vy * vy + vz * vz;
			double maxSpeedSq = baseSpeedPerTick * baseSpeedPerTick;
			if (totalSpeedSq > maxSpeedSq) {
				double scale3D = baseSpeedPerTick / Math.sqrt(totalSpeedSq);
				vx *= scale3D;
				vy *= scale3D;
				vz *= scale3D;
			}
		}

		// 4. Unloaded-chunk lag guard: prevents freezing inside unloaded chunks at 60 BPS
		if (vx != 0.0 || vz != 0.0) {
			double chunkScale = getChunkLoadScale(player, vx, vz);
			vx *= chunkScale;
			vz *= chunkScale;
		}

		// Client deltaMovement stays 100% smooth (vy = 0.0 when hovering) -> ZERO camera shake/lag!
		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	/**
	 * Packet-only Anti-Kick & Ground Spoofing inside LocalPlayer.sendPosition() (@At("HEAD")).
	 * Applies the required server anti-kick dip and ground flag strictly to the outgoing packet
	 * and restores the client position in onPostSendPosition -> 0 camera jitter and 0 extra packets!
	 */
	public void onPreSendPosition(LocalPlayer player) {
		spoofingPacketState = false;
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}

		savedRealOnGround = player.onGround();
		savedX = player.getX();
		savedY = player.getY();
		savedZ = player.getZ();
		spoofingPacketState = true;

		double packetYOffset = 0.0;
		boolean spoofGround = false;

		if (tickCounter >= nextAntiKickTick) {
			tickCounter = 0;
			nextAntiKickTick = randomInterval();
			double noise = (ThreadLocalRandom.current().nextDouble() - 0.5) * 0.0018;
			packetYOffset = -(IRRATIONAL_DIP_BASE + noise);
		} else if (tickCounter == 1) {
			spoofGround = true;
		}

		if (player.getDeltaMovement().y < -0.05 || player.fallDistance > 1.2F) {
			spoofGround = true;
		}

		if (packetYOffset != 0.0 && player.level() != null
			&& player.level().noCollision(player, player.getBoundingBox().move(0.0, packetYOffset, 0.0))) {
			player.setPosRaw(savedX, savedY + packetYOffset, savedZ);
		}
		if (spoofGround) {
			player.setOnGround(true);
		}
	}

	/**
	 * Restores exact client coordinates and onGround state at @At("TAIL") of LocalPlayer.sendPosition().
	 */
	public void onPostSendPosition(LocalPlayer player) {
		if (!spoofingPacketState || player == null) {
			return;
		}
		player.setPosRaw(savedX, savedY, savedZ);
		player.setOnGround(savedRealOnGround);
		spoofingPacketState = false;
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

	private static int randomInterval() {
		return ThreadLocalRandom.current().nextInt(28, 46);
	}
}
