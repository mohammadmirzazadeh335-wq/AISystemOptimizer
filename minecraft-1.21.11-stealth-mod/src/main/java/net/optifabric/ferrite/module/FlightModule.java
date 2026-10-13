package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.SectionPos;
import net.minecraft.network.protocol.game.ServerboundMovePlayerPacket;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

public final class FlightModule {
	public static final FlightModule INSTANCE = new FlightModule();

	/**
	 * Target speed: 60.0 blocks per second (3.0 blocks per tick at 20 TPS).
	 */
	public static final double TARGET_BLOCKS_PER_SECOND = 60.0;
	public static final double TICKS_PER_SECOND = 20.0;
	public static final double MAX_SPEED_PER_TICK = TARGET_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 3.0

	/**
	 * Exact Vanilla Minecraft 1.21.11 gravity & jump constants:
	 * - First airborne fall tick: (0.0 - 0.08) * 0.9800000190734863 = -0.0784000015258789D
	 * - Vanilla jump velocity: (double) 0.42F = 0.41999998688697815D
	 * - Vanilla air friction multiplier: 0.91F
	 */
	private static final double VANILLA_FIRST_FALL_DELTA = -0.0784000015258789D;
	private static final double VANILLA_GRAVITY = 0.08D;
	private static final double VANILLA_AIR_DRAG = 0.9800000190734863D;
	private static final double VANILLA_HORIZONTAL_FRICTION = 0.91D;

	private volatile boolean enabled = false;
	/**
	 * 0 = Auto SMP Bypass (60 BPS + Sub-Packet Split + Gravity Wave + Auto-Setback Tuner for smp3.mcsh.io)
	 * 1 = Strict Vanilla AirHop Bypass (Grim / Vulcan / Matrix / NCP simulation-compliant jump arcs)
	 * 2 = Glide Pulse Bypass (Continuous -0.0315D fall with periodic step recovery)
	 * 3 = Raw 60 BPS Turbo
	 */
	private volatile int bypassMode = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int moveRampTicks = 0;
	private int ticksSinceLastSetback = 100;

	/**
	 * Auto-adaptive speed multiplier: starts at 1.0 (60 BPS).
	 * If smp3.mcsh.io sends a teleport setback, automatically tunes down to the
	 * exact speed threshold accepted by the server's anti-cheat and smoothly recovers.
	 */
	private double adaptiveSpeedMultiplier = 1.0;
	private double prevHorizontalSpeed = 0.0;

	/**
	 * Anchor Y coordinate used to keep the player's average altitude constant
	 * and lock the rendered camera Y so the gravity wave never shakes the screen.
	 */
	private double anchorY = Double.NaN;
	private double lastTickX = 0.0;
	private double lastTickY = 0.0;
	private double lastTickZ = 0.0;

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
		bypassMode = (bypassMode + 1) % 4;
		adaptiveSpeedMultiplier = 1.0;
		tickCounter = 0;
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.tickCounter = 0;
		this.moveRampTicks = 0;
		this.ticksSinceLastSetback = 100;
		this.adaptiveSpeedMultiplier = 1.0;
		this.prevHorizontalSpeed = 0.0;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player != null) {
			player.getAbilities().flying = false;
			player.resetFallDistance();
			if (state) {
				this.anchorY = player.getY();
				this.lastTickX = player.getX();
				this.lastTickY = player.getY();
				this.lastTickZ = player.getZ();
			} else {
				this.anchorY = Double.NaN;
				player.setDeltaMovement(Vec3.ZERO);
				if (mc.getWindow() != null && mc.options != null) {
					boolean shiftActuallyDown =
						GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
					mc.options.keyShift.setDown(shiftActuallyDown);
				}
			}
		}
	}

	/**
	 * Called from ClientPacketListenerMixin when the server (smp3.mcsh.io) sends a
	 * ClientboundPlayerPositionPacket setback/teleport.
	 */
	public void onServerSetback(LocalPlayer player, double teleportY) {
		if (!enabled || player == null) {
			return;
		}
		this.anchorY = teleportY;
		this.tickCounter = 0;
		this.moveRampTicks = 0;
		this.prevHorizontalSpeed = 0.0;

		if (ticksSinceLastSetback < 40) {
			// Server anti-cheat rejected the previous speed delta; step down smoothly
			adaptiveSpeedMultiplier = Math.max(0.22, adaptiveSpeedMultiplier * 0.72);
		} else {
			adaptiveSpeedMultiplier = Math.max(0.32, adaptiveSpeedMultiplier * 0.85);
		}
		this.ticksSinceLastSetback = 0;
	}

	public void onTick(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		// Reset state across dimension switches, respawns, or server reconnects
		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			anchorY = player.getY();
			lastTickX = player.getX();
			lastTickY = player.getY();
			lastTickZ = player.getZ();
			tickCounter = 0;
			moveRampTicks = 0;
			prevHorizontalSpeed = 0.0;
			player.setDeltaMovement(Vec3.ZERO);
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();

		lastTickX = player.getX();
		lastTickY = player.getY();
		lastTickZ = player.getZ();
		tickCounter++;
		ticksSinceLastSetback++;

		if (Double.isNaN(anchorY)) {
			anchorY = player.getY();
		}

		// Gradually recover adaptive speed when flying cleanly without server setbacks
		if (ticksSinceLastSetback > 35 && adaptiveSpeedMultiplier < 1.0) {
			adaptiveSpeedMultiplier = Math.min(1.0, adaptiveSpeedMultiplier + 0.015);
		}

		// 1. Read vertical input (Space = Up, Left Shift = Down)
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

		// 2. Compute vertical velocity (vy) with ZERO GroundSpoof and ZERO Hover-0.0 flags
		double vy = computeBypassVerticalVelocity(player, jumpDown, shiftDown);

		// 3. Read WASD input and compute horizontal velocity
		Vec2 moveInput = (mc.screen == null && player.input != null)
			? player.input.getMoveVector()
			: Vec2.ZERO;

		double moveLeft = moveInput.x;
		double moveForward = moveInput.y;
		double inputLenSq = moveLeft * moveLeft + moveForward * moveForward;

		double vx = 0.0;
		double vz = 0.0;

		if (inputLenSq > 1.0E-4) {
			moveRampTicks = Math.min(moveRampTicks + 1, 4);
			double invLen = 1.0 / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;

			double targetSpeed = computeBypassHorizontalSpeed(player);
			prevHorizontalSpeed = targetSpeed;

			double yawRad = player.getYRot() * Mth.DEG_TO_RAD;
			double sinYaw = Math.sin(yawRad);
			double cosYaw = Math.cos(yawRad);

			vx = (moveLeft * cosYaw - moveForward * sinYaw) * targetSpeed;
			vz = (moveLeft * sinYaw + moveForward * cosYaw) * targetSpeed;

			// Unloaded-chunk lag guard
			double chunkScale = getChunkLoadScale(player, vx, vz);
			vx *= chunkScale;
			vz *= chunkScale;
		} else {
			moveRampTicks = 0;
			prevHorizontalSpeed = 0.0;
		}

		// 4. Safe landing cushion: when descending close to solid ground, cushion vy
		// so the player lands softly with zero fall damage and 100% legitimate onGround state
		if (vy < -0.32 && isSolidGroundWithin(player, Math.abs(vy) + 1.8)) {
			vy = -0.22;
			anchorY = player.getY();
		}

		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	private double computeBypassHorizontalSpeed(LocalPlayer player) {
		double noise = ThreadLocalRandom.current().nextGaussian() * 0.00075;

		if (bypassMode == 1) {
			// Mode 1: Strict Vanilla AirHop Bypass (Grim / Vulcan / Matrix / NCP)
			// Follows exact 0.91F horizontal air friction decay with jump-tick sprint burst
			int phase = tickCounter % 6;
			if (phase == 1) {
				return 0.62D + noise;
			}
			return Math.max(0.29D, prevHorizontalSpeed * VANILLA_HORIZONTAL_FRICTION) + noise;
		}

		if (bypassMode == 2) {
			// Mode 2: Glide Pulse Bypass
			double base = 1.15D * adaptiveSpeedMultiplier;
			if (tickCounter % 4 == 0) {
				return prevHorizontalSpeed * VANILLA_HORIZONTAL_FRICTION;
			}
			return base + noise;
		}

		if (bypassMode == 3) {
			// Mode 3: Raw 60 BPS Turbo
			return MAX_SPEED_PER_TICK + noise;
		}

		// Mode 0 (Default — AUTO_SMP_BYPASS for smp3.mcsh.io):
		// Targets 60 BPS (3.0 blocks/tick) scaled by adaptiveSpeedMultiplier,
		// with a periodic 0.91F friction compliance tick every 5 ticks so anti-cheats
		// checking horizontal deceleration ratios pass cleanly.
		double ramp = switch (moveRampTicks) {
			case 1 -> 0.38;
			case 2 -> 0.68;
			case 3 -> 0.88;
			default -> 1.0;
		};
		double maxAllowed = MAX_SPEED_PER_TICK * adaptiveSpeedMultiplier * ramp;
		if (tickCounter % 5 == 0 && prevHorizontalSpeed > 0.35) {
			return prevHorizontalSpeed * VANILLA_HORIZONTAL_FRICTION;
		}
		return maxAllowed + Mth.clamp(noise, -0.002, 0.002);
	}

	private double computeBypassVerticalVelocity(LocalPlayer player, boolean jumpDown, boolean shiftDown) {
		double vNoise = (ThreadLocalRandom.current().nextDouble() - 0.5) * 0.0014;
		double maxClimbSpeed = Math.min(MAX_SPEED_PER_TICK * adaptiveSpeedMultiplier, 1.85);

		if (jumpDown && !shiftDown) {
			// Climbing: every 5th tick insert a brief gravity decay tick (-0.0784) so
			// anti-cheats checking continuous upward motion reset their ascension counter
			double climb = (tickCounter % 5 == 0)
				? VANILLA_FIRST_FALL_DELTA
				: Math.min(maxClimbSpeed, 1.15) + vNoise;
			anchorY = player.getY() + climb;
			return climb;
		}

		if (shiftDown && !jumpDown) {
			double descend = -Math.min(maxClimbSpeed, 1.15) + vNoise;
			anchorY = player.getY() + descend;
			return descend;
		}

		// Hovering / Horizontal Flight (Neither Space nor Shift held):
		// NEVER use vy == 0.0 (which flags Flight Hover on tick 2 of every anti-cheat!).
		if (bypassMode == 1) {
			// Strict AirHop: 6-tick Vanilla jump & gravity parabola Around anchorY
			int hopPhase = tickCounter % 6;
			return switch (hopPhase) {
				case 0 -> 0.41999998688697815D; // Exact (double) 0.42F Vanilla jump
				case 1 -> (0.41999998688697815D - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // +0.3332
				case 2 -> VANILLA_FIRST_FALL_DELTA; // -0.0784
				case 3 -> (VANILLA_FIRST_FALL_DELTA - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // -0.1552
				case 4 -> -0.2305D;
				default -> (anchorY - player.getY());
			};
		}

		if (bypassMode == 2) {
			// Glide Pulse: continuous -0.0325D fall (< -0.03125D) with recovery every 10 ticks
			if (tickCounter % 10 == 0) {
				return (anchorY - player.getY()) + 0.01;
			}
			return -0.0328D + vNoise;
		}

		// Mode 0 & Mode 3: 4-tick Vanilla Gravity Micro-Wave around anchorY:
		// Ticks 0, 1, 2 move downward with dy < -0.03125D (including exact -0.0784 first-fall constant)
		// so server clientIsFloating is false 75% of the time and dy is NEVER 0.0!
		// Tick 3 smoothly returns to anchorY.
		int wavePhase = tickCounter % 4;
		return switch (wavePhase) {
			case 0 -> VANILLA_FIRST_FALL_DELTA + vNoise; // -0.0784 (< -0.03125)
			case 1 -> -0.0352D + vNoise;                 // -0.0352 (< -0.03125)
			case 2 -> -0.0326D + vNoise;                 // -0.0326 (< -0.03125)
			default -> Mth.clamp(anchorY - player.getY(), -0.18D, 0.18D);
		};
	}

	/**
	 * Called at @At("HEAD") of LocalPlayer.sendPosition().
	 * When moving at high horizontal speed (> 1.15 blocks/tick), sends 1 intermediate
	 * halfway sub-step packet with honest onGround state so each packet's deltaXZ is halved,
	 * bypassing Paper/Spigot "moved wrongly!" (0.0625) and single-packet speed checks.
	 */
	public void onPreSendPosition(LocalPlayer player) {
		if (!enabled || player == null || player.connection == null || player.tickCount < 5) {
			return;
		}
		if (ticksSinceLastSetback < 3) {
			return;
		}

		double dx = player.getX() - lastTickX;
		double dy = player.getY() - lastTickY;
		double dz = player.getZ() - lastTickZ;
		double horizSq = dx * dx + dz * dz;

		// Only split into a halfway sub-step when horizontal delta exceeds 1.15 blocks/tick
		if (horizSq > (1.15 * 1.15)) {
			double midX = lastTickX + dx * 0.5;
			double midY = lastTickY + dy * 0.5;
			double midZ = lastTickZ + dz * 0.5;
			// NEVER spoof onGround = true in mid-air; use actual block collision state
			boolean midOnGround = player.onGround() && isSolidGroundWithin(player, 0.08);
			player.connection.send(
				new ServerboundMovePlayerPacket.Pos(midX, midY, midZ, midOnGround, player.horizontalCollision)
			);
		}
	}

	public void onPostSendPosition(LocalPlayer player) {
		// No fake coordinate or fake onGround state to restore — everything sent is consistent!
	}

	/**
	 * Stabilizes the rendered camera Y on screen so the anti-hover gravity micro-wave
	 * is completely invisible to the player's eyes (100% smooth camera).
	 */
	public double getStabilizedCameraY(Entity cameraEntity, double originalCameraY) {
		Minecraft mc = Minecraft.getInstance();
		if (!enabled || cameraEntity != mc.player || Double.isNaN(anchorY)) {
			return originalCameraY;
		}
		double eyeOffset = originalCameraY - cameraEntity.getY();
		double targetCamY = anchorY + eyeOffset;
		if (Math.abs(originalCameraY - targetCamY) < 0.65) {
			return targetCamY;
		}
		return originalCameraY;
	}

	private boolean isSolidGroundWithin(LocalPlayer player, double distanceBelow) {
		if (player.level() == null) {
			return false;
		}
		AABB checkBox = player.getBoundingBox().expandTowards(0.0, -distanceBelow, 0.0);
		return !player.level().noCollision(player, checkBox);
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
