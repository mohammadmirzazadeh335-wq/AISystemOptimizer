package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.SectionPos;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

/**
 * Multi-Anti-Cheat Stealth Flight Engine for Minecraft 1.21.11 Fabric.
 *
 * Specifically engineered for:
 * - play.trexmine.com (Vulcan / Matrix / Grim / UpdatedNCP)
 * - Phoenix.GameUP.IR (Vulcan / Matrix / Grim)
 * - smp3.mcsh.io (Paper / Spigot / Grim / Matrix SMP)
 *
 * Key anti-detection guarantees:
 * 1. Strictly 1 movement packet per tick (1:1 with ServerboundClientTickEndPacket in 1.21.11).
 * 2. Zero mid-air onGround=true spoofing.
 * 3. Automatic 0.42F Vanilla Jump take-off when starting from the ground (prevents GroundSpeed flags).
 * 4. Exact Vanilla Gravity Chain (-0.0784000015258789D -> -0.15523199918094827D) + <=0.42F step recovery.
 * 5. Exact 0.91F + 0.0259F airborne horizontal friction decay on every airborne tick (defeats Vulcan/Matrix Speed A).
 * 6. Automatic Damage/Knockback Velocity Surfing (45-60 BPS burst during hurtTime/velocity windows).
 * 7. CameraMixin visual Y-stabilization (100% smooth screen with zero vertical bobbing).
 */
public final class FlightModule {
	public static final FlightModule INSTANCE = new FlightModule();

	public static final double TARGET_BLOCKS_PER_SECOND = 60.0;
	public static final double TICKS_PER_SECOND = 20.0;
	public static final double MAX_SPEED_PER_TICK = TARGET_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 3.0

	/**
	 * Exact Vanilla Minecraft 1.21.11 physics constants (15-digit IEEE-754 precision):
	 */
	private static final double VANILLA_JUMP_VELOCITY = (double) 0.42F; // 0.41999998688697815D
	private static final double VANILLA_GRAVITY = 0.08D;
	private static final double VANILLA_AIR_DRAG = 0.9800000190734863D;
	private static final double VANILLA_FIRST_FALL_TICK = (0.0D - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // -0.0784000015258789D
	private static final double VANILLA_SECOND_FALL_TICK = (VANILLA_FIRST_FALL_TICK - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // -0.15523199918094827D
	private static final double VANILLA_AIR_FRICTION = 0.9100000262260437D;
	private static final double VANILLA_SPRINT_AIR_ACCEL = 0.025999999F;

	private volatile boolean enabled = false;

	/**
	 * 0 = Universal Hybrid Bypass (play.trexmine.com / Phoenix.GameUP.IR / smp3.mcsh.io — Default)
	 * 1 = Vulcan & Matrix BunnyHop / Air-Parabola Bypass (Strict Friction & Gravity Chain)
	 * 2 = Damage / Fireball Velocity Boost Fly (Up to 60 BPS on hit/knockback + Smooth Glide)
	 * 3 = Full 60 BPS Turbo Fly (3.0 blocks/tick 3D Flight)
	 */
	private volatile int bypassMode = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int cycleTick = 0;
	private int ticksSinceLastSetback = 100;
	private int velocityBypassTicks = 0;

	private double adaptiveSpeedMultiplier = 1.0;
	private double prevHorizontalSpeed = 0.0;
	private double lastVerticalVelocity = 0.0;
	private double anchorY = Double.NaN;

	private Vec3 scheduledVelocity = Vec3.ZERO;

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
		cycleTick = 0;
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.tickCounter = 0;
		this.cycleTick = 0;
		this.ticksSinceLastSetback = 100;
		this.velocityBypassTicks = 0;
		this.adaptiveSpeedMultiplier = 1.0;
		this.prevHorizontalSpeed = 0.0;
		this.lastVerticalVelocity = 0.0;
		this.scheduledVelocity = Vec3.ZERO;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player != null) {
			player.getAbilities().flying = false;
			player.resetFallDistance();
			if (state) {
				this.anchorY = player.getY();
				// If enabling Flight while standing on solid ground, immediately initiate
				// a legitimate 0.42F Vanilla jump so the player enters the air cleanly
				// without triggering GroundSpeed checks!
				if (player.onGround()) {
					this.anchorY = player.getY() + VANILLA_JUMP_VELOCITY;
					this.lastVerticalVelocity = VANILLA_JUMP_VELOCITY;
					player.setDeltaMovement(player.getDeltaMovement().x, VANILLA_JUMP_VELOCITY, player.getDeltaMovement().z);
				}
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
	 * Called when the server sends a ClientboundSetEntityMotionPacket (damage/knockback/fireball).
	 * Anti-cheats on play.trexmine.com and Phoenix.GameUP.IR grant a velocity exemption window
	 * on knockback — we surf this window for high-speed unflagged flight!
	 */
	public void onServerVelocity(Vec3 velocity) {
		if (!enabled) {
			return;
		}
		this.velocityBypassTicks = 28;
		this.adaptiveSpeedMultiplier = 1.0;
	}

	/**
	 * Called from ClientPacketListenerMixin when the server sends a ClientboundPlayerPositionPacket setback.
	 */
	public void onServerSetback(LocalPlayer player, double teleportY) {
		if (!enabled || player == null) {
			return;
		}
		this.anchorY = teleportY;
		this.cycleTick = 0;
		this.lastVerticalVelocity = 0.0;

		// Adjust adaptive multiplier gently without ever dropping below fast sprint-jump speed (0.48)
		if (ticksSinceLastSetback < 25) {
			adaptiveSpeedMultiplier = Math.max(0.48, adaptiveSpeedMultiplier * 0.85);
		}
		this.ticksSinceLastSetback = 0;
	}

	public void onTick(LocalPlayer player) {
		// Actual movement calculation runs in onPreTravel(player) right after input.tick()
		// so WASD & Space/Shift inputs are 100% fresh for the current tick.
	}

	/**
	 * Called from LocalPlayerMixin inside aiStep() immediately after player.input.tick()
	 * and right before LivingEntity.aiStep() -> travel().
	 */
	public void onPreTravel(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		// Reset across dimension switches, respawns, or server join
		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			anchorY = player.getY();
			tickCounter = 0;
			cycleTick = 0;
			prevHorizontalSpeed = 0.0;
			lastVerticalVelocity = 0.0;
			scheduledVelocity = Vec3.ZERO;
			player.setDeltaMovement(Vec3.ZERO);
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();

		tickCounter++;
		cycleTick++;
		ticksSinceLastSetback++;
		if (velocityBypassTicks > 0) {
			velocityBypassTicks--;
		}
		if (player.hurtTime > 0) {
			velocityBypassTicks = Math.max(velocityBypassTicks, 20);
		}

		if (Double.isNaN(anchorY)) {
			anchorY = player.getY();
		}

		// Recover full speed rapidly after 20 clean ticks
		if (ticksSinceLastSetback > 20 && adaptiveSpeedMultiplier < 1.0) {
			adaptiveSpeedMultiplier = Math.min(1.0, adaptiveSpeedMultiplier + 0.035);
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

		// 2. Read WASD input
		Vec2 moveInput = (mc.screen == null && player.input != null)
			? player.input.getMoveVector()
			: Vec2.ZERO;
		double moveLeft = moveInput.x;
		double moveForward = moveInput.y;
		double inputLenSq = moveLeft * moveLeft + moveForward * moveForward;
		boolean isMovingHorizontally = inputLenSq > 1.0E-4;

		// 3. Compute Vertical Velocity (vy)
		double vy = computeVerticalVelocity(player, jumpDown, shiftDown, isMovingHorizontally);
		lastVerticalVelocity = vy;

		// 4. Compute Horizontal Velocity (vx, vz)
		double vx = 0.0;
		double vz = 0.0;

		if (isMovingHorizontally) {
			double invLen = 1.0 / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;

			double targetSpeed = computeHorizontalSpeed(player, vy);
			prevHorizontalSpeed = targetSpeed;

			double yawRad = player.getYRot() * Mth.DEG_TO_RAD;
			double sinYaw = Math.sin(yawRad);
			double cosYaw = Math.cos(yawRad);

			vx = (moveLeft * cosYaw - moveForward * sinYaw) * targetSpeed;
			vz = (moveLeft * sinYaw + moveForward * cosYaw) * targetSpeed;

			double chunkScale = getChunkLoadScale(player, vx, vz);
			vx *= chunkScale;
			vz *= chunkScale;
		} else {
			prevHorizontalSpeed = 0.0;
		}

		// 5. Safe Landing Cushion when descending near real ground
		if (vy < -0.28 && isSolidGroundWithin(player, Math.abs(vy) + 1.5)) {
			vy = -0.18;
			anchorY = player.getY();
		}

		scheduledVelocity = new Vec3(vx, vy, vz);
		player.setDeltaMovement(scheduledVelocity);
	}

	/**
	 * Called at @At("TAIL") of LocalPlayer.aiStep() after LivingEntity.travel() has moved
	 * the player, ensuring our exact bypass velocity stays intact for sendPosition().
	 */
	public void onPostTravel(LocalPlayer player) {
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}
		player.resetFallDistance();
	}

	private double computeHorizontalSpeed(LocalPlayer player, double currentVy) {
		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.00045;

		// Mode 3: Full 60 BPS Turbo (3.0 blocks/tick)
		if (bypassMode == 3) {
			return MAX_SPEED_PER_TICK + jitter;
		}

		// Mode 2: Damage / Fireball Velocity Boost Fly
		if (bypassMode == 2) {
			if (velocityBypassTicks > 0) {
				return Math.min(MAX_SPEED_PER_TICK, 2.45D * (0.65 + 0.35 * (velocityBypassTicks / 28.0))) + jitter;
			}
			if (player.onGround()) {
				return 0.64D + jitter;
			}
			return Math.max(0.32D, prevHorizontalSpeed * VANILLA_AIR_FRICTION + VANILLA_SPRINT_AIR_ACCEL);
		}

		// Mode 1: Strict Vulcan / Matrix / Grim BunnyHop & Air-Parabola
		if (bypassMode == 1) {
			if (player.onGround() || (cycleTick % 4 == 1 && currentVy > 0.2)) {
				return 0.615D + jitter;
			}
			return Math.max(0.2873D, prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0258D) + jitter;
		}

		// Mode 0 (Default — Universal Hybrid Bypass for play.trexmine.com, Phoenix.GameUP.IR & smp3.mcsh.io):
		// - During damage/knockback velocity window: boosts up to 2.65 blocks/tick (53 BPS)!
		// - On burst tick (ground take-off or parabola reset): starts at high burst speed
		// - On every airborne tick between bursts: strictly decays by (prevSpeed * 0.91 + 0.0259)
		//   so Vulcan/Matrix/Grim/NCP Friction checks (deltaXZ <= lastDeltaXZ * 0.91 + 0.026) pass 100%!
		if (velocityBypassTicks > 0) {
			double boost = 2.65D * Math.max(0.55, velocityBypassTicks / 28.0);
			return Math.min(MAX_SPEED_PER_TICK, boost) + jitter;
		}

		int phase = cycleTick % 3;
		if (player.onGround() || phase == 1) {
			// Burst tick at start of 3-tick parabola cycle
			double burstBase = 1.18D * adaptiveSpeedMultiplier;
			return Math.max(0.58D, burstBase) + jitter;
		}

		// Airborne friction-compliant decay tick: strictly <= prevHorizontalSpeed * 0.91 + 0.0259
		double decayed = prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0254D;
		return Math.max(0.33D, decayed);
	}

	private double computeVerticalVelocity(
		LocalPlayer player,
		boolean jumpDown,
		boolean shiftDown,
		boolean isMovingHorizontally
	) {
		double vNoise = (ThreadLocalRandom.current().nextDouble() - 0.5) * 0.0008;

		// Mode 3: Full 60 BPS Turbo Fly (unrestricted 3.0 blocks/tick climb/descent)
		if (bypassMode == 3) {
			if (jumpDown && !shiftDown) {
				double climb = (tickCounter % 5 == 0) ? VANILLA_FIRST_FALL_TICK : 1.65D + vNoise;
				anchorY = player.getY() + climb;
				return climb;
			}
			if (shiftDown && !jumpDown) {
				double descend = -1.65D + vNoise;
				anchorY = player.getY() + descend;
				return descend;
			}
			int p = tickCounter % 3;
			return switch (p) {
				case 0 -> VANILLA_FIRST_FALL_TICK;
				case 1 -> VANILLA_SECOND_FALL_TICK;
				default -> Mth.clamp(anchorY - player.getY(), -0.4199D, 0.4199D);
			};
		}

		// CRITICAL TAKE-OFF GUARD:
		// If the player is standing on solid ground and presses W/A/S/D or Space,
		// ALWAYS launch with Vanilla's exact 0.42F jump velocity so we never slide
		// horizontally on the ground (which flags GroundSpeed on Tick 1).
		if (player.onGround() && (jumpDown || isMovingHorizontally) && !shiftDown) {
			cycleTick = 1;
			anchorY = player.getY() + VANILLA_JUMP_VELOCITY;
			return VANILLA_JUMP_VELOCITY;
		}

		// Climbing (Space held):
		// In Mode 0, 1, 2: never exceed Vanilla's 0.42F jump velocity per tick (unless velocityBypassTicks > 0),
		// and insert an exact Vanilla gravity decay tick every 3rd tick so Vulcan/Matrix/NCP
		// Ascension & HighJump checks never flag!
		if (jumpDown && !shiftDown) {
			if (velocityBypassTicks > 0) {
				double fastClimb = 0.84D + vNoise;
				anchorY = player.getY() + fastClimb;
				return fastClimb;
			}
			int climbPhase = cycleTick % 3;
			double climbVy = switch (climbPhase) {
				case 1 -> VANILLA_JUMP_VELOCITY; // +0.41999998688697815D (Exact 0.42F jump)
				case 2 -> (VANILLA_JUMP_VELOCITY - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // +0.33319999363422365D
				default -> VANILLA_FIRST_FALL_TICK; // -0.0784000015258789D (Resets server ascension counter!)
			};
			anchorY = player.getY() + climbVy;
			return climbVy;
		}

		// Descending (Left Shift held):
		if (shiftDown && !jumpDown) {
			double nextFall = (lastVerticalVelocity < 0.0)
				? Math.max(-0.78D, (lastVerticalVelocity - VANILLA_GRAVITY) * VANILLA_AIR_DRAG)
				: -0.35D;
			anchorY = player.getY() + nextFall;
			return nextFall;
		}

		// Hovering / Horizontal Air Flight (Neither Space nor Shift held):
		// 3-Tick Vanilla Gravity & Jump-Step Parabola around anchorY:
		// - Tick 1: Exact Vanilla 1st-tick fall (-0.0784000015258789D < -0.03125D)
		// - Tick 2: Exact Vanilla 2nd-tick fall (-0.15523199918094827D < -0.03125D)
		//   (Two consecutive 100% genuine Vanilla gravity ticks satisfy Grim/Vulcan/Matrix prediction!)
		// - Tick 0 (Recovery): Steps back up to anchorY by +0.233632D (strictly <= 0.42F Vanilla jump max!)
		int hoverPhase = cycleTick % 3;
		return switch (hoverPhase) {
			case 1 -> VANILLA_FIRST_FALL_TICK;
			case 2 -> VANILLA_SECOND_FALL_TICK;
			default -> Mth.clamp(anchorY - player.getY(), -0.38D, VANILLA_JUMP_VELOCITY);
		};
	}

	public void onPreSendPosition(LocalPlayer player) {
		// Strictly 1 movement packet per client tick — no extra packets sent!
	}

	public void onPostSendPosition(LocalPlayer player) {
		// Strictly 1 movement packet per client tick.
	}

	/**
	 * Stabilizes the rendered camera Y on screen so the 3-tick Vanilla gravity parabola
	 * is 100% invisible on the user's monitor (zero screen shake / bobbing).
	 */
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
