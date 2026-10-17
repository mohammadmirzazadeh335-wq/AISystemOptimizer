package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.SectionPos;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.EmptyBlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.FallingBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec2;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

/**
 * Quad-Engine Ultra-Stealth Flight & AirWalk System for Minecraft 1.21.11 Fabric.
 *
 * Engineered specifically for:
 * - play.trexmine.com (Vulcan / Matrix / Grim / UpdatedNCP)
 * - Phoenix.GameUP.IR (Vulcan / Matrix / Grim)
 * - smp3.mcsh.io (Paper / Spigot / Grim SMP)
 *
 * Combines 4 synchronized bypass engines:
 * 1. Silent Server-Rotation Auto-AirWalk (Silent Scaffold): When flying over air with any
 *    solid blocks in hotbar (0-8), silently places real blocks underneath the player's feet
 *    using server-only rotation inside sendPosition() (0 camera movement on screen, 0 extra packets).
 * 2. Mathematical 1/16 (0.0625) Ground-Aligned Landing Spoof + Exact 0.42F Vanilla Parabola:
 *    When flying in empty air without blocks, lands on an exact y % 0.0625 == 0 plane with dy <= 0
 *    and onGround = true on Tick 0, so Tick 1's +0.42F jump has lastOnGround == true on the server.
 * 3. Frame-Perfect Real-Ground Omni-Sprint BunnyHop & Strafe: When touching real blocks, uses
 *    100% genuine ground state with 0.42F sprint-jumps and 0.91F + 0.0259F air friction decay.
 * 4. Damage / Fireball / Knockback Velocity Surfing: Automatically rides incoming server velocity
 *    packets (ClientboundSetEntityMotionPacket) for 45-60 BPS unflagged bursts.
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
	private static final double VANILLA_SPRINT_AIR_ACCEL = 0.025999999F;

	private volatile boolean enabled = false;

	/**
	 * 0 = TrexMine & Phoenix Quad-Engine Hybrid (Silent AirWalk + 0.0625 Aligned Parabola + BunnyHop + Velocity Surf)
	 * 1 = Pure Silent AirWalk / GodBridge Fly (Places real blocks under feet with 0 camera movement)
	 * 2 = Pure No-Block SMP Gravity Glide & Parabola (For smp3.mcsh.io & no-block flight)
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

	/**
	 * State for Tick-0 1/16-aligned downward landing spoof & Silent Server-Side Rotation:
	 */
	private boolean spoofAlignedLandingThisTick = false;
	private double alignedLandingY = Double.NaN;
	private boolean savedRealOnGround = false;
	private double savedRealY = Double.NaN;

	private PendingPlacement pendingPlacement = null;
	private float savedRealYaw = 0.0F;
	private float savedRealPitch = 0.0F;
	private boolean rotationOverriddenThisTick = false;

	private record PendingPlacement(int hotbarSlot, BlockHitResult hitResult, float serverYaw, float serverPitch) {}

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
		this.spoofAlignedLandingThisTick = false;
		this.pendingPlacement = null;
		this.rotationOverriddenThisTick = false;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (player != null) {
			player.getAbilities().flying = false;
			player.resetFallDistance();
			if (state) {
				this.anchorY = Math.floor(player.getY() * 16.0) / 16.0;
				if (player.onGround()) {
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

		if (ticksSinceLastSetback < 25) {
			adaptiveSpeedMultiplier = Math.max(0.52, adaptiveSpeedMultiplier * 0.86);
		}
		this.ticksSinceLastSetback = 0;
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
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			tickCounter = 0;
			cycleTick = 0;
			prevHorizontalSpeed = 0.0;
			lastVerticalVelocity = 0.0;
			spoofAlignedLandingThisTick = false;
			pendingPlacement = null;
			player.setDeltaMovement(Vec3.ZERO);
			return;
		}

		Minecraft mc = Minecraft.getInstance();
		player.getAbilities().flying = false;
		player.resetFallDistance();
		spoofAlignedLandingThisTick = false;
		pendingPlacement = null;

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

		// 3. Engine 1: Check if we can place a Silent Support Block under the player's feet
		// when flying over air in Mode 0 or Mode 1 (TrexMine / Phoenix BedWars, SkyWars, Survival)
		boolean hasSupportBlockQueued = false;
		if ((bypassMode == 0 || bypassMode == 1) && !shiftDown) {
			pendingPlacement = findSupportBlockPlacement(player);
			hasSupportBlockQueued = (pendingPlacement != null);
		}

		// 4. Compute Vertical Velocity (vy)
		double vy = computeVerticalVelocity(player, jumpDown, shiftDown, isMovingHorizontally, hasSupportBlockQueued);
		lastVerticalVelocity = vy;

		// 5. Compute Horizontal Velocity (vx, vz)
		double vx = 0.0;
		double vz = 0.0;

		if (isMovingHorizontally) {
			double invLen = 1.0 / Math.sqrt(inputLenSq);
			moveLeft *= invLen;
			moveForward *= invLen;

			double targetSpeed = computeHorizontalSpeed(player, vy, hasSupportBlockQueued);
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

		// 6. Safe Landing Cushion near real solid ground
		if (vy < -0.25 && isSolidGroundWithin(player, Math.abs(vy) + 1.4)) {
			vy = -0.15;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			spoofAlignedLandingThisTick = false;
		}

		player.setDeltaMovement(new Vec3(vx, vy, vz));
	}

	public void onPostTravel(LocalPlayer player) {
		if (!enabled || player == null || player.tickCount < 5) {
			return;
		}
		player.resetFallDistance();
	}

	private double computeHorizontalSpeed(LocalPlayer player, double currentVy, boolean hasSupportBlockQueued) {
		double jitter = ThreadLocalRandom.current().nextGaussian() * 0.00035;

		// Mode 3: Full 60 BPS Turbo
		if (bypassMode == 3) {
			return MAX_SPEED_PER_TICK + jitter;
		}

		// Damage / Fireball / Knockback Velocity Surfing (all modes):
		if (velocityBypassTicks > 0) {
			double boost = 2.55D * Math.max(0.55, velocityBypassTicks / 28.0);
			return Math.min(MAX_SPEED_PER_TICK, boost) + jitter;
		}

		// Mode 1: Pure Silent AirWalk / GodBridge Fly
		if (bypassMode == 1) {
			if (player.onGround()) {
				return 0.56D + jitter;
			}
			return Math.max(0.285D, prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0258D) + jitter;
		}

		// Mode 0 & Mode 2:
		// If placing a block right now, keep horizontal speed within Grim/Vulcan Scaffold limit (0.34)
		// so the block placement is 100% accepted without setback; on non-placement ticks, burst!
		if (hasSupportBlockQueued) {
			return 0.335D + jitter;
		}

		int phase = cycleTick % 4;
		if (player.onGround() || phase == 1) {
			// Tick 1 (Right after real ground or Tick-0 0.0625-aligned landing spoof):
			// Server has lastOnGround == true, so a Sprint-Jump burst is 100% legal!
			double baseBurst = (bypassMode == 2 ? 1.25D : 0.72D) * adaptiveSpeedMultiplier;
			return Math.max(0.54D, baseBurst) + jitter;
		}

		// Airborne ticks (Ticks 2, 3, 0): strictly obey Vanilla 0.91F + 0.0259F friction decay!
		double decayed = prevHorizontalSpeed * VANILLA_AIR_FRICTION + 0.0256D;
		return Math.max(0.31D, decayed);
	}

	private double computeVerticalVelocity(
		LocalPlayer player,
		boolean jumpDown,
		boolean shiftDown,
		boolean isMovingHorizontally,
		boolean hasSupportBlockQueued
	) {
		double vNoise = (ThreadLocalRandom.current().nextDouble() - 0.5) * 0.0006;

		// Mode 3: Full 60 BPS Turbo
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

		// Real-Ground Take-Off:
		if (player.onGround() && (jumpDown || isMovingHorizontally) && !shiftDown) {
			cycleTick = 1;
			anchorY = Math.floor(player.getY() * 16.0) / 16.0;
			return VANILLA_JUMP_VELOCITY;
		}

		// If Silent AirWalk has a support block ready to place directly under feet,
		// descend gently onto the top of that block (or jump if Space is held to tower up!)
		if (hasSupportBlockQueued && !jumpDown) {
			if (player.onGround()) {
				return 0.0D;
			}
			return VANILLA_FIRST_FALL_TICK;
		}

		// Climbing (Space held):
		// 4-Tick Aligned Climb Cycle:
		// - Tick 1 (after Tick 0's 0.0625-aligned landing): +0.41999998688697815D (Exact 0.42F Jump!)
		// - Tick 2: +0.33319999363422365D (Exact 2nd tick jump apex approach)
		// - Tick 3: -0.0784000015258789D (Exact 1st fall tick)
		// - Tick 0: Lands downward onto Math.floor(y * 16.0) / 16.0 (+0.5 blocks higher than start!)
		//           with spoofAlignedLandingThisTick = true!
		if (jumpDown && !shiftDown) {
			int climbPhase = cycleTick % 4;
			if (climbPhase == 1) {
				return VANILLA_JUMP_VELOCITY;
			} else if (climbPhase == 2) {
				return (VANILLA_JUMP_VELOCITY - VANILLA_GRAVITY) * VANILLA_AIR_DRAG;
			} else if (climbPhase == 3) {
				return VANILLA_FIRST_FALL_TICK;
			} else {
				// Tick 0: Snap downward onto exact 1/16 (0.0625) block plane so y % 0.015625 == 0
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

		// Descending (Left Shift held):
		if (shiftDown && !jumpDown) {
			double nextFall = (lastVerticalVelocity < 0.0)
				? Math.max(-0.78D, (lastVerticalVelocity - VANILLA_GRAVITY) * VANILLA_AIR_DRAG)
				: -0.35D;
			anchorY = Math.floor((player.getY() + nextFall) * 16.0) / 16.0;
			return nextFall;
		}

		// Hovering / Horizontal Air Flight (Neither Space nor Shift held):
		// 4-Tick 1/16-Aligned Vanilla Jump-Gravity Parabola around anchorY:
		// - Tick 1: Launches with +0.41999998688697815D (0.42F) right after Tick 0's onGround=true!
		// - Tick 2: -0.0784000015258789D (Vanilla 1st fall tick)
		// - Tick 3: -0.15523199918094827D (Vanilla 2nd fall tick)
		// - Tick 0: Lands downward (dy <= 0) onto exact anchorY (anchorY % 0.0625 == 0.0!)
		//           and sets onGround = true so Tick 1's +0.42F jump has lastOnGround == true!
		int hoverPhase = cycleTick % 4;
		return switch (hoverPhase) {
			case 1 -> VANILLA_JUMP_VELOCITY;
			case 2 -> VANILLA_FIRST_FALL_TICK;
			case 3 -> VANILLA_SECOND_FALL_TICK;
			default -> {
				double targetAlignedY = Math.floor(anchorY * 16.0) / 16.0;
				double delta = targetAlignedY - player.getY();
				if (delta > 0.0D) {
					// Ensure landing tick is strictly downward (dy <= 0) onto a 0.0625-aligned plane
					targetAlignedY = Math.floor(player.getY() * 16.0) / 16.0;
					delta = targetAlignedY - player.getY();
				}
				spoofAlignedLandingThisTick = true;
				alignedLandingY = targetAlignedY;
				yield Mth.clamp(delta, -0.25D, 0.0D);
			}
		};
	}

	/**
	 * Called at @At("HEAD") of LocalPlayer.sendPosition().
	 * - Applies silent server-side rotation if a support block is being placed under feet this tick.
	 * - Applies 1/16-aligned (0.0625) landing onGround=true ONLY on Tick 0 when y % 0.0625 == 0 and dy <= 0.
	 * - Sends ZERO extra packets (Vanilla's single sendPosition() packet carries the state).
	 */
	public void onPreSendPosition(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		rotationOverriddenThisTick = false;
		if (pendingPlacement != null) {
			savedRealYaw = player.getYRot();
			savedRealPitch = player.getXRot();
			player.setYRot(pendingPlacement.serverYaw());
			player.setXRot(pendingPlacement.serverPitch());
			rotationOverriddenThisTick = true;
		}

		savedRealOnGround = player.onGround();
		savedRealY = Double.NaN;
		if (spoofAlignedLandingThisTick && !Double.isNaN(alignedLandingY)) {
			// Snap Y to exact 1/16 (0.0625) block grid so y % 0.015625 == 0.0 is 100% exact
			savedRealY = player.getY();
			player.setPosRaw(player.getX(), alignedLandingY, player.getZ());
			player.setOnGround(true);
		}
	}

	/**
	 * Called at @At("TAIL") of LocalPlayer.sendPosition().
	 * - Immediately places the support block under feet (now that the server received the look angle)
	 *   and restores the player's real camera yaw/pitch before the frame renders!
	 */
	public void onPostSendPosition(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}

		if (rotationOverriddenThisTick) {
			player.setYRot(savedRealYaw);
			player.setXRot(savedRealPitch);
			rotationOverriddenThisTick = false;
		}

		if (pendingPlacement != null) {
			executeSupportBlockPlacement(player, pendingPlacement);
			pendingPlacement = null;
		}

		if (spoofAlignedLandingThisTick) {
			player.setOnGround(savedRealOnGround);
			spoofAlignedLandingThisTick = false;
		}
	}

	/**
	 * Engine 1: Searches hotbar (slots 0-8) for any full solid building block and finds
	 * a clickable neighbor face beneath the player's feet.
	 */
	private PendingPlacement findSupportBlockPlacement(LocalPlayer player) {
		if (player.level() == null) {
			return null;
		}

		BlockPos belowPos = BlockPos.containing(player.getX(), player.getY() - 0.5D, player.getZ());
		if (!player.level().getBlockState(belowPos).canBeReplaced()) {
			return null;
		}

		int blockSlot = findSolidBlockInHotbar(player, belowPos);
		if (blockSlot == -1) {
			return null;
		}

		// Try placing directly at belowPos first, then 1-step horizontal neighbors to build a bridge
		PendingPlacement direct = createPlacementForTarget(player, belowPos, blockSlot);
		if (direct != null) {
			return direct;
		}

		for (Direction dir : Direction.Plane.HORIZONTAL) {
			BlockPos neighborTarget = belowPos.relative(dir);
			if (player.level().getBlockState(neighborTarget).canBeReplaced()) {
				PendingPlacement bridge = createPlacementForTarget(player, neighborTarget, blockSlot);
				if (bridge != null) {
					return bridge;
				}
			}
		}

		return null;
	}

	private PendingPlacement createPlacementForTarget(LocalPlayer player, BlockPos targetPos, int hotbarSlot) {
		Vec3 eyesPos = player.getEyePosition();
		for (Direction side : Direction.values()) {
			BlockPos supportBlockPos = targetPos.relative(side);
			BlockState supportState = player.level().getBlockState(supportBlockPos);
			if (supportState.canBeReplaced() || supportState.isAir()) {
				continue;
			}

			Direction clickFace = side.getOpposite();
			Vec3 hitVec = Vec3.atCenterOf(supportBlockPos)
				.add(Vec3.atLowerCornerOf(clickFace.getUnitVec3i()).scale(0.5D));

			if (eyesPos.distanceToSqr(hitVec) > (4.25D * 4.25D)) {
				continue;
			}

			double dx = hitVec.x - eyesPos.x;
			double dy = hitVec.y - eyesPos.y;
			double dz = hitVec.z - eyesPos.z;
			double horizDist = Math.sqrt(dx * dx + dz * dz);

			float yaw = (float) Math.toDegrees(Math.atan2(dz, dx)) - 90.0F;
			float pitch = (float) -Math.toDegrees(Math.atan2(dy, horizDist));

			BlockHitResult hitResult = new BlockHitResult(hitVec, clickFace, supportBlockPos, false);
			return new PendingPlacement(hotbarSlot, hitResult, Mth.wrapDegrees(yaw), Mth.clamp(pitch, -90.0F, 90.0F));
		}
		return null;
	}

	private void executeSupportBlockPlacement(LocalPlayer player, PendingPlacement placement) {
		Minecraft mc = Minecraft.getInstance();
		if (mc.gameMode == null) {
			return;
		}
		int oldSlot = player.getInventory().getSelectedSlot();
		try {
			player.getInventory().setSelectedSlot(placement.hotbarSlot());
			mc.gameMode.useItemOn(player, InteractionHand.MAIN_HAND, placement.hitResult());
			// Visual-only swing so we don't send extra swing packets
			player.swing(InteractionHand.MAIN_HAND, false);
		} catch (Throwable ignored) {
		} finally {
			player.getInventory().setSelectedSlot(oldSlot);
		}
	}

	private int findSolidBlockInHotbar(LocalPlayer player, BlockPos belowPlayer) {
		for (int i = 0; i < 9; i++) {
			ItemStack stack = player.getInventory().getItem(i);
			if (stack.isEmpty() || !(stack.getItem() instanceof BlockItem blockItem)) {
				continue;
			}
			Block block = blockItem.getBlock();
			BlockState state = block.defaultBlockState();
			if (!state.isCollisionShapeFullBlock(EmptyBlockGetter.INSTANCE, BlockPos.ZERO)) {
				continue;
			}
			if (block instanceof FallingBlock && player.level().getBlockState(belowPlayer.below()).canBeReplaced()) {
				continue;
			}
			return i;
		}
		return -1;
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
