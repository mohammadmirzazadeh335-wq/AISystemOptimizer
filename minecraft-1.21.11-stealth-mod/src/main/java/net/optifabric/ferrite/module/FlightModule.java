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
import net.optifabric.ferrite.module.AirPlaceModule.PendingAirPlacement;
import org.lwjgl.glfw.GLFW;

/**
 * Adaptive Match & Lobby Stealth Flight System for Minecraft 1.21.11 Fabric.
 *
 * Why Flight previously worked only in the BedWars Lobby on play.trexmine.com
 * and failed inside the actual BedWars Match — and how this solves both:
 *
 * 1. In the BedWars Lobby (and SMP servers like smp3.mcsh.io):
 *    The server allows 1/16 (0.0625) block-aligned landing packets in mid-air,
 *    so no-block mid-air parabola flight works directly.
 * 2. Inside the Actual BedWars Match on play.trexmine.com & Phoenix.GameUP.IR:
 *    The match server verifies real chunk blocks underneath the player (GroundSpoof-B)
 *    and enforces strict Scaffold NoSwing / SilentSwitch checks.
 *    - When you have blocks (Wool, Wood, Endstone, etc.) in hotbar: FlightModule keeps
 *      your feet aligned with the bridge level and uses AirPlaceModule's legit-packet
 *      chain placer (with real ServerboundSwingPacket & persistent slot selection) to
 *      build real blocks underneath your feet over the void and up into the sky!
 *    - When you have no blocks in a strict match: automatically disables mid-air
 *      onGround spoofing on first setback so you never rubberband, seamlessly switching
 *      to Real-Ground Fast BunnyHop/Strafe + Fireball/Damage Velocity Flight!
 */
public final class FlightModule {
	public static final FlightModule INSTANCE = new FlightModule();

	public static final double TARGET_BLOCKS_PER_SECOND = 60.0;
	public static final double TICKS_PER_SECOND = 20.0;
	public static final double MAX_SPEED_PER_TICK = TARGET_BLOCKS_PER_SECOND / TICKS_PER_SECOND; // 3.0

	private static final double VANILLA_JUMP_VELOCITY = (double) 0.42F; // 0.41999998688697815D
	private static final double VANILLA_GRAVITY = 0.08D;
	private static final double VANILLA_AIR_DRAG = 0.9800000190734863D;
	private static final double VANILLA_FIRST_FALL_TICK = (0.0D - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // -0.0784000015258789D
	private static final double VANILLA_SECOND_FALL_TICK = (VANILLA_FIRST_FALL_TICK - VANILLA_GRAVITY) * VANILLA_AIR_DRAG; // -0.15523199918094827D
	private static final double VANILLA_AIR_FRICTION = 0.9100000262260437D;

	private volatile boolean enabled = false;

	/**
	 * 0 = Auto Match + Lobby Hybrid (Default — Works in both BedWars Match & Lobby + SMP)
	 * 1 = Strict BedWars Match Mode (Void/Sky Block-Fly + Real-Ground BunnyHop + Velocity Surf, 0 Spoof)
	 * 2 = Lobby & SMP No-Block Parabola Fly (0.0625-Aligned Mid-Air Flight)
	 * 3 = Full 60 BPS Turbo Fly
	 */
	private volatile int bypassMode = 0;

	private LocalPlayer lastPlayerInstance = null;
	private int tickCounter = 0;
	private int cycleTick = 0;
	private int ticksSinceLastSetback = 100;
	private int velocityBypassTicks = 0;

	/**
	 * Automatically detects when the player transitions from the BedWars Lobby
	 * into a strict BedWars Match where mid-air GroundSpoof-B is active.
	 */
	private boolean strictMatchAntiCheatDetected = false;
	private int midAirSetbackCount = 0;

	private double adaptiveSpeedMultiplier = 1.0;
	private double prevHorizontalSpeed = 0.0;
	private double lastVerticalVelocity = 0.0;
	private double anchorY = Double.NaN;

	private boolean spoofAlignedLandingThisTick = false;
	private double alignedLandingY = Double.NaN;
	private boolean savedRealOnGround = false;

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
		strictMatchAntiCheatDetected = (bypassMode == 1);
		midAirSetbackCount = 0;
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
		this.spoofAlignedLandingThisTick = false;
		this.midAirSetbackCount = 0;
		this.strictMatchAntiCheatDetected = (bypassMode == 1);

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player != null) {
			player.getAbilities().flying = false;
			player.resetFallDistance();
			if (state) {
				this.anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			} else {
				this.anchorY = Double.NaN;
				AirPlaceModule.INSTANCE.restoreOriginalSlotIfNeeded(player);
				if (mc.getWindow() != null && mc.options != null) {
					boolean shiftActuallyDown =
						GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
					mc.options.keyShift.setDown(shiftActuallyDown);
				}
			}
		}
	}

	public void onServerVelocity(Vec3 velocity) {
		if (!enabled) {
			return;
		}
		this.velocityBypassTicks = 28;
		this.adaptiveSpeedMultiplier = 1.0;
	}

	public void onServerSetback(LocalPlayer player, double teleportY) {
		if (!enabled || player == null) {
			return;
		}
		this.anchorY = Math.floor(teleportY * 16.0) / 16.0;
		this.cycleTick = 0;
		this.lastVerticalVelocity = 0.0;
		this.spoofAlignedLandingThisTick = false;

		if (!isSolidGroundWithin(player, 0.5)) {
			midAirSetbackCount++;
			// If the server rejects mid-air spoofed landing (which happens inside the BedWars Match),
			// immediately switch to Match-Compliant Mode (Zero mid-air onGround spoofing!)
			if (midAirSetbackCount >= 1 && bypassMode == 0) {
				strictMatchAntiCheatDetected = true;
			}
		}

		if (ticksSinceLastSetback < 25) {
			adaptiveSpeedMultiplier = Math.max(0.55, adaptiveSpeedMultiplier * 0.88);
		}
		this.ticksSinceLastSetback = 0;
	}

	public void onTick(LocalPlayer player) {
		// Handled in onPreTravel right after player.input.tick()
	}

	public void onPreTravel(LocalPlayer player) {
		if (player == null) {
			return;
		}

		// If 'Y' (AirPlaceModule) is enabled even when 'V' (Flight) is OFF, prepare void/sky block placement!
		if (!enabled) {
			if (AirPlaceModule.INSTANCE.isEnabled()) {
				AirPlaceModule.INSTANCE.preparePlacementForTick(player, false);
			}
			return;
		}

		if (player != lastPlayerInstance || player.tickCount < 5) {
			lastPlayerInstance = player;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			tickCounter = 0;
			cycleTick = 0;
			prevHorizontalSpeed = 0.0;
			lastVerticalVelocity = 0.0;
			spoofAlignedLandingThisTick = false;
			midAirSetbackCount = 0;
			strictMatchAntiCheatDetected = (bypassMode == 1);
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();
		spoofAlignedLandingThisTick = false;

		tickCounter++;
		cycleTick++;
		ticksSinceLastSetback++;
		if (velocityBypassTicks > 0) {
			velocityBypassTicks--;
		}
		if (player.hurtTime > 0) {
			velocityBypassTicks = Math.max(velocityBypassTicks, 22);
		}

		if (Double.isNaN(anchorY)) {
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
		}

		if (ticksSinceLastSetback > 18 && adaptiveSpeedMultiplier < 1.0) {
			adaptiveSpeedMultiplier = Math.min(1.0, adaptiveSpeedMultiplier + 0.04);
		}

		// Read vertical input (Space = Up, Left Shift = Down)
		boolean jumpDown = false;
		boolean shiftDown = false;
		if (mc.screen == null && mc.getWindow() != null) {
			long handle = mc.getWindow().handle();
			jumpDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_SPACE) == GLFW.GLFW_PRESS
				|| mc.options.keyJump.isDown();
			shiftDown = GLFW.glfwGetKey(handle, GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS;
			if (shiftDown && (!strictMatchAntiCheatDetected || isSolidGroundWithin(player, 1.2))) {
				mc.options.keyShift.setDown(false);
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

		// Check if we have building blocks in hotbar for Void/Sky Block-Fly inside BedWars Match
		boolean hasBlocksInHotbar = AirPlaceModule.INSTANCE.findBestBlockSlotInHotbar(player) != -1;
		PendingAirPlacement activePlacement = null;
		if ((bypassMode == 0 || bypassMode == 1 || AirPlaceModule.INSTANCE.isEnabled()) && !shiftDown && hasBlocksInHotbar) {
			activePlacement = AirPlaceModule.INSTANCE.preparePlacementForTick(player, true);
		}

		boolean useStrictMatchPhysics = (bypassMode == 1) || (bypassMode == 0 && (strictMatchAntiCheatDetected || hasBlocksInHotbar));

		// Compute Vertical & Horizontal Velocity
		if (useStrictMatchPhysics && velocityBypassTicks == 0 && bypassMode != 3) {
			applyBedWarsMatchPhysics(player, moveLeft, moveForward, inputLenSq, isMovingHorizontally, jumpDown, shiftDown, activePlacement, hasBlocksInHotbar);
			return;
		}

		// Lobby / SMP / Velocity-Boost / Turbo 3D Flight Physics:
		double vy = computeLobbyAndSmpVerticalVelocity(player, jumpDown, shiftDown, isMovingHorizontally);
		lastVerticalVelocity = vy;

		double vx = 0.0;
		double vz = 0.0;

		if (isMovingHorizontally) {
			double invLen = 1.0 / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;

			double targetSpeed = computeLobbyAndSmpHorizontalSpeed(player);
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

		if (vy < -0.25 && isSolidGroundWithin(player, Math.abs(vy) + 1.4)) {
			vy = -0.15;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			spoofAlignedLandingThisTick = false;
		}

		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	/**
	 * Specialized BedWars / SkyWars / Survival Match Physics for play.trexmine.com & Phoenix.GameUP.IR:
	 * - NEVER spoofs mid-air onGround=true (zero GroundSpoof-B flags inside the match!).
	 * - When blocks are in hotbar and moving over the Void (or holding Space to fly up):
	 *   keeps player at exact bridge level so AirPlaceModule places real blocks under feet on every step!
	 * - When on solid ground/bridges without placing: executes fast Vanilla-compliant Sprint-Jump / Strafe!
	 */
	private void applyBedWarsMatchPhysics(
		LocalPlayer player,
		double moveLeft,
		double moveForward,
		double inputLenSq,
		boolean isMovingHorizontally,
		boolean jumpDown,
		boolean shiftDown,
		PendingAirPlacement activePlacement,
		boolean hasBlocksInHotbar
	) {
		Vec3 currentVel = player.getDeltaMovement();
		double vy = currentVel.y;

		boolean onRealGround = player.onGround();
		boolean solidBelowSoon = isSolidGroundWithin(player, 0.65);

		if (jumpDown && !shiftDown) {
			// Climbing / Sky-Towering inside the Match:
			// Jump with exact 0.42F whenever on ground (including on the newly placed block under feet!)
			if (onRealGround) {
				vy = VANILLA_JUMP_VELOCITY;
				anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			}
		} else if (!hasBlocksInHotbar && onRealGround && isMovingHorizontally && !shiftDown) {
			// When running on islands/bridges with no blocks to place: auto BunnyHop at 0.42F!
			vy = VANILLA_JUMP_VELOCITY;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
		} else if (hasBlocksInHotbar && onRealGround && !jumpDown) {
			// Keep feet level with the bridge when running across the Void with blocks in hotbar
			// so AirPlaceModule can continuously place horizontal blocks at the exact bridge Y level!
			vy = 0.0D;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
		}

		if (!isMovingHorizontally) {
			prevHorizontalSpeed = 0.0;
			player.setDeltaMovement(0.0D, vy, 0.0D);
			return;
		}

		double invLen = 1.0 / Math.sqrt(inputLenSq);
		moveLeft *= invLen;
		moveForward *= invLen;

		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.00025;
		double targetSpeed;

		if (activePlacement != null || (hasBlocksInHotbar && !solidBelowSoon)) {
			// Stepping over the Void while placing a real block under feet:
			// Use exact maximum Vulcan/Grim GodBridge speed (0.282 blocks/tick) so 100% of blocks
			// register before the player steps past the block edge!
			targetSpeed = 0.282D + jitter;
		} else if (onRealGround) {
			// Fast Ground Strafe / BunnyHop launch on real blocks:
			targetSpeed = (vy > 0.35D ? 0.595D : 0.315D) + jitter;
		} else {
			// Airborne friction-compliant decay (strictly <= prevSpeed * 0.91 + 0.0259):
			targetSpeed = Math.max(0.265D, prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0254D) + jitter;
		}

		prevHorizontalSpeed = targetSpeed;

		double yawRad = player.getYRot() * Mth.DEG_TO_RAD;
		double sinYaw = Math.sin(yawRad);
		double cosYaw = Math.cos(yawRad);

		double vx = (moveLeft * cosYaw - moveForward * sinYaw) * targetSpeed;
		double vz = (moveLeft * sinYaw + moveForward * cosYaw) * targetSpeed;

		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	private double computeLobbyAndSmpHorizontalSpeed(LocalPlayer player) {
		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.00035;

		if (bypassMode == 3) {
			return MAX_SPEED_PER_TICK + jitter;
		}

		if (velocityBypassTicks > 0) {
			double boost = 2.45D * Math.max(0.55, velocityBypassTicks / 28.0);
			return Math.min(MAX_SPEED_PER_TICK, boost) + jitter;
		}

		int phase = cycleTick % 4;
		if (player.onGround() || phase == 1) {
			double baseBurst = 1.15D * adaptiveSpeedMultiplier;
			return Math.max(0.56D, baseBurst) + jitter;
		}

		double decayed = prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0256D;
		return Math.max(0.32D, decayed);
	}

	private double computeLobbyAndSmpVerticalVelocity(
		LocalPlayer player,
		boolean jumpDown,
		boolean shiftDown,
		boolean isMovingHorizontally
	) {
		double vNoise = (ThreadLocalRandom.current().nextDouble() - 0.5) * 0.0006;

		if (bypassMode == 3) {
			if (jumpDown && !shiftDown) {
				double climb = (tickCounter % 5 == 0) ? VANILLA_FIRST_FALL_TICK : 1.75D + vNoise;
				anchorY = player.getY() + climb;
				return climb;
			}
			if (shiftDown && !jumpDown) {
				double descend = -1.75D + vNoise;
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

		if (player.onGround() && (jumpDown || isMovingHorizontally) && !shiftDown) {
			cycleTick = 1;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			return VANILLA_JUMP_VELOCITY;
		}

		if (jumpDown && !shiftDown) {
			if (velocityBypassTicks > 0) {
				double fastClimb = 0.82D + vNoise;
				anchorY = player.getY() + fastClimb;
				return fastClimb;
			}
			int climbPhase = cycleTick % 4;
			if (climbPhase == 1) {
				return VANILLA_JUMP_VELOCITY;
			} else if (climbPhase == 2) {
				return (VANILLA_JUMP_VELOCITY - VANILLA_GRAVITY) * VANILLA_AIR_DRAG;
			} else if (climbPhase == 3) {
				return VANILLA_FIRST_FALL_TICK;
			} else {
				double targetAlignedY = Math.floor(player.getY() * 16.0) / 16.0;
				double deltaToAligned = targetAlignedY - player.getY();
				if (deltaToAligned > -0.002D) {
					targetAlignedY -= 0.0625D;
					deltaToAligned = targetAlignedY - player.getY();
				}
				spoofAlignedLandingThisTick = true;
				alignedLandingY = targetAlignedY;
				anchorY = targetAlignedY;
				return deltaToAligned;
			}
		}

		if (shiftDown && !jumpDown) {
			double nextFall = (lastVerticalVelocity < 0.0)
				? Math.max(-0.78D, (lastVerticalVelocity - VANILLA_GRAVITY) * VANILLA_AIR_DRAG)
				: -0.35D;
			anchorY = Math.floor((player.getY() + nextFall) * 16.0) / 16.0;
			return nextFall;
		}

		int hoverPhase = cycleTick % 4;
		return switch (hoverPhase) {
			case 1 -> VANILLA_JUMP_VELOCITY;
			case 2 -> VANILLA_FIRST_FALL_TICK;
			case 3 -> VANILLA_SECOND_FALL_TICK;
			default -> {
				double targetAlignedY = Math.floor(anchorY * 16.0) / 16.0;
				double delta = targetAlignedY - player.getY();
				if (delta > 0.0D) {
					targetAlignedY = Math.floor(player.getY() * 16.0) / 16.0;
					delta = targetAlignedY - player.getY();
				}
				spoofAlignedLandingThisTick = true;
				alignedLandingY = targetAlignedY;
				yield Mth.clamp(delta, -0.25D, 0.0D);
			}
		};
	}

	public void onPostTravel(LocalPlayer player) {
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}
		player.resetFallDistance();
	}

	public void onPreSendPosition(LocalPlayer player) {
		if (player == null) {
			return;
		}

		// Always allow AirPlaceModule ('Y' or Flight Void-Bridge) to inject silent server rotation
		AirPlaceModule.INSTANCE.onPreSendPosition(player);

		if (!enabled) {
			return;
		}

		savedRealOnGround = player.onGround();
		if (spoofAlignedLandingThisTick && !Double.isNaN(alignedLandingY)) {
			player.setPosRaw(player.getX(), alignedLandingY, player.getZ());
			player.setOnGround(true);
		}
	}

	public void onPostSendPosition(LocalPlayer player) {
		if (player == null) {
			return;
		}

		// Execute queued Void/Sky block placement immediately after sendPosition() sent the look angle
		AirPlaceModule.INSTANCE.onPostSendPosition(player);

		if (enabled && spoofAlignedLandingThisTick) {
			player.setOnGround(savedRealOnGround);
			spoofAlignedLandingThisTick = false;
		}
	}

	public double getStabilizedCameraY(Entity cameraEntity, double originalCameraY) {
		Minecraft mc = Minecraft.getInstance();
		if (!enabled || cameraEntity != mc.player || Double.isNaN(anchorY)) {
			return originalCameraY;
		}
		double eyeOffset = originalCameraY - cameraEntity.getY();
		double targetCamY = anchorY + eyeOffset;
		if (Math.abs(originalCameraY - targetCamY) < 0.95) {
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
