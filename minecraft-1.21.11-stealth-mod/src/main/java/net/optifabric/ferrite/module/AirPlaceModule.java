package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.EmptyBlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.FallingBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

/**
 * Ultra-Stealth Void, Sky & Mid-Air Block Placement Engine (Toggled / Activated via 'Y' key).
 *
 * Combines 3 stealth techniques to place blocks over the Void, in the Sky, and in Mid-Air
 * on play.trexmine.com, Phoenix.GameUP.IR, and smp3.mcsh.io:
 *
 * 1. Multi-Block 3D Chain Search (GodBridge / Void-Saver / Sky-Tower):
 *    Automatically finds the nearest reachable solid block face within 4.5 blocks (under feet,
 *    behind on island edge, or 2-3 blocks away) and chains real blocks under the player's feet
 *    as they walk over the void or hold Space to climb into the sky.
 * 2. Pure Mid-Air / Sky Packet AirPlace (BlockPlaceContext.replacingClickedOnBlock exploit):
 *    When no adjacent block exists within 4.5 blocks (deep over the void or high in the sky, or
 *    when right-clicking at the sky), dispatches a BlockHitResult targeting the replaceable Air
 *    block itself (insideBlock = true, Direction.UP) with synchronized server rotation.
 * 3. Full Vulcan / Grim / Matrix Anti-Cheat Stealth:
 *    - Sends real ServerboundSwingPacket (defeats Scaffold NoSwing).
 *    - Holds the block slot across placement ticks with delayed restore (defeats 0ms SilentSwitch).
 *    - Applies humanized Gaussian micro-jitter to server-only yaw/pitch inside sendPosition()
 *      while keeping the player's screen camera 100% motionless.
 */
public final class AirPlaceModule {
	public static final AirPlaceModule INSTANCE = new AirPlaceModule();

	private volatile boolean enabled = false;

	private PendingAirPlacement queuedPlacement = null;
	private float savedRealYaw = 0.0F;
	private float savedRealPitch = 0.0F;
	private boolean rotationActiveThisTick = false;

	/**
	 * Persistent hotbar slot management to avoid 0ms same-tick slot switching
	 * (which flags Vulcan Scaffold-K / Grim BadPackets on play.trexmine.com).
	 */
	private int originalHotbarSlot = -1;
	private int ticksSinceLastPlace = 100;
	private int placeCooldownTicks = 0;

	public record PendingAirPlacement(
		int hotbarSlot,
		BlockHitResult hitResult,
		float serverYaw,
		float serverPitch,
		boolean isTowerUp
	) {}

	private AirPlaceModule() {}

	public boolean isEnabled() {
		return enabled;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		this.queuedPlacement = null;
		this.rotationActiveThisTick = false;
		this.placeCooldownTicks = 0;

		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		if (!state && player != null) {
			restoreOriginalSlotIfNeeded(player);
		}
	}

	/**
	 * Prepares a void/sky/mid-air block placement for the current tick.
	 * Called automatically when 'Y' (AirPlaceModule) is enabled, OR by FlightModule ('V')
	 * when flying over the void in BedWars/SkyWars matches!
	 */
	public PendingAirPlacement preparePlacementForTick(LocalPlayer player, boolean calledFromFlight) {
		if (player == null || player.level() == null) {
			return null;
		}

		Minecraft mc = Minecraft.getInstance();
		if (mc.screen != null || player.isUsingItem()) {
			return null;
		}

		ticksSinceLastPlace++;
		if (placeCooldownTicks > 0) {
			placeCooldownTicks--;
		}

		// Restore weapon slot smoothly after 4 ticks of not placing any blocks
		if (ticksSinceLastPlace > 4 && !enabled) {
			restoreOriginalSlotIfNeeded(player);
		} else if (ticksSinceLastPlace > 8) {
			restoreOriginalSlotIfNeeded(player);
		}

		int blockSlot = findBestBlockSlotInHotbar(player);
		if (blockSlot == -1) {
			restoreOriginalSlotIfNeeded(player);
			return null;
		}

		boolean jumpDown = mc.getWindow() != null
			&& (GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_SPACE) == GLFW.GLFW_PRESS
				|| mc.options.keyJump.isDown());
		boolean rightClickDown = mc.options != null && mc.options.keyUse.isDown();

		// 1. Check block directly beneath the player's feet (and predicted next step over void)
		double footY = Math.floor(player.getY() - 0.01D) - 1.0D;
		BlockPos underFeet = BlockPos.containing(player.getX(), footY, player.getZ());

		Vec3 vel = player.getDeltaMovement();
		BlockPos aheadUnderFeet = BlockPos.containing(
			player.getX() + vel.x * 1.35D,
			footY,
			player.getZ() + vel.z * 1.35D
		);

		// A) Sky-Tower Mode: When holding Space over a solid block (or in air), place directly under feet as we ascend
		if (jumpDown) {
			BlockPos towerTarget = BlockPos.containing(player.getX(), Math.floor(player.getY()) - 1.0D, player.getZ());
			if (canPlaceAt(player, towerTarget)) {
				PendingAirPlacement towerPlace = findLegitSupportOrAirPlacement(player, towerTarget, blockSlot, true);
				if (towerPlace != null) {
					this.queuedPlacement = towerPlace;
					return towerPlace;
				}
			}
		}

		// B) Void / Sky Bridge Under Feet: Place under current feet first, then predicted next step
		if (canPlaceAt(player, underFeet)) {
			PendingAirPlacement underPlace = findLegitSupportOrAirPlacement(player, underFeet, blockSlot, false);
			if (underPlace != null) {
				this.queuedPlacement = underPlace;
				return underPlace;
			}
		}

		if (!aheadUnderFeet.equals(underFeet) && canPlaceAt(player, aheadUnderFeet)) {
			PendingAirPlacement aheadPlace = findLegitSupportOrAirPlacement(player, aheadUnderFeet, blockSlot, false);
			if (aheadPlace != null) {
				this.queuedPlacement = aheadPlace;
				return aheadPlace;
			}
		}

		// C) Crosshair Sky / Void Mid-Air Placement:
		// When 'Y' is enabled and the user presses Right-Click while aiming at empty Sky or Void
		// (HitResult.Type.MISS), place a block in mid-air 3.2 blocks in front of their crosshair!
		if (enabled && !calledFromFlight && rightClickDown && placeCooldownTicks == 0) {
			if (mc.hitResult == null || mc.hitResult.getType() == HitResult.Type.MISS) {
				Vec3 eyePos = player.getEyePosition();
				Vec3 lookVec = player.getViewVector(1.0F);
				Vec3 targetVec = eyePos.add(lookVec.scale(3.0D));
				BlockPos skyTarget = BlockPos.containing(targetVec);
				if (canPlaceAt(player, skyTarget)) {
					PendingAirPlacement skyPlace = findLegitSupportOrAirPlacement(player, skyTarget, blockSlot, false);
					if (skyPlace != null) {
						placeCooldownTicks = 3;
						this.queuedPlacement = skyPlace;
						return skyPlace;
					}
				}
			}
		}

		return null;
	}

	/**
	 * Finds either:
	 * 1) A direct adjacent solid block face to click against, OR
	 * 2) A 1-to-2 block bridge chain from the nearest solid block within 4.5 blocks, OR
	 * 3) A pure mid-air Packet AirPlace targeting the replaceable Air block itself.
	 */
	private PendingAirPlacement findLegitSupportOrAirPlacement(
		LocalPlayer player,
		BlockPos targetPos,
		int blockSlot,
		boolean isTowerUp
	) {
		// 1. Try direct placement against any adjacent solid block of targetPos
		PendingAirPlacement direct = buildSupportFacePlacement(player, targetPos, blockSlot, isTowerUp);
		if (direct != null) {
			return direct;
		}

		// 2. Try 1-step horizontal & vertical neighbor chain (builds a connecting block from island edge!)
		for (Direction dir : Direction.values()) {
			BlockPos step1 = targetPos.relative(dir);
			if (canPlaceAt(player, step1)) {
				PendingAirPlacement chain1 = buildSupportFacePlacement(player, step1, blockSlot, false);
				if (chain1 != null) {
					return chain1;
				}
			}
		}

		// 3. Try 2-step bridge chain (when 2 blocks out over the void)
		for (Direction dir1 : Direction.Plane.HORIZONTAL) {
			BlockPos step1 = targetPos.relative(dir1);
			for (Direction dir2 : Direction.values()) {
				if (dir2 == dir1.getOpposite()) {
					continue;
				}
				BlockPos step2 = step1.relative(dir2);
				if (canPlaceAt(player, step2)) {
					PendingAirPlacement chain2 = buildSupportFacePlacement(player, step2, blockSlot, false);
					if (chain2 != null) {
						return chain2;
					}
				}
			}
		}

		// 4. Pure Mid-Air / Void / Sky Packet AirPlace (when zero solid blocks exist within 4.5 blocks):
		// Targets targetPos itself with Direction.UP and insideBlock = true so BlockPlaceContext
		// replaces the Air block directly in mid-air!
		Vec3 eyesPos = player.getEyePosition();
		Vec3 hitVec = new Vec3(targetPos.getX() + 0.5D, targetPos.getY() + 0.5D, targetPos.getZ() + 0.5D);
		if (eyesPos.distanceToSqr(hitVec) <= (4.5D * 4.5D)) {
			float[] rots = computeHumanizedRotations(eyesPos, hitVec);
			BlockHitResult airHitResult = new BlockHitResult(hitVec, Direction.UP, targetPos, true);
			return new PendingAirPlacement(blockSlot, airHitResult, rots[0], rots[1], isTowerUp);
		}

		return null;
	}

	private PendingAirPlacement buildSupportFacePlacement(
		LocalPlayer player,
		BlockPos targetPos,
		int blockSlot,
		boolean isTowerUp
	) {
		Vec3 eyesPos = player.getEyePosition();

		// Prefer clicking UP face when towering, or horizontal faces when bridging over void
		Direction[] searchOrder = isTowerUp
			? new Direction[] { Direction.DOWN, Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST, Direction.UP }
			: new Direction[] { Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST, Direction.DOWN, Direction.UP };

		for (Direction side : searchOrder) {
			BlockPos neighborPos = targetPos.relative(side);
			BlockState neighborState = player.level().getBlockState(neighborPos);
			if (neighborState.canBeReplaced() || neighborState.isAir()) {
				continue;
			}

			Direction clickFace = side.getOpposite();
			Vec3 hitVec = Vec3.atCenterOf(neighborPos)
				.add(Vec3.atLowerCornerOf(clickFace.getUnitVec3i()).scale(0.5D));

			// Must be within 4.35 blocks reach
			if (eyesPos.distanceToSqr(hitVec) > (4.35D * 4.35D)) {
				continue;
			}

			float[] rots = computeHumanizedRotations(eyesPos, hitVec);
			BlockHitResult hitResult = new BlockHitResult(hitVec, clickFace, neighborPos, false);
			return new PendingAirPlacement(blockSlot, hitResult, rots[0], rots[1], isTowerUp);
		}
		return null;
	}

	private float[] computeHumanizedRotations(Vec3 eyesPos, Vec3 hitVec) {
		ThreadLocalRandom rng = ThreadLocalRandom.current();
		double dx = hitVec.x - eyesPos.x;
		double dy = hitVec.y - eyesPos.y;
		double dz = hitVec.z - eyesPos.z;
		double horizDist = Math.sqrt(dx * dx + dz * dz);

		// Add subtle human Gaussian micro-jitter (±0.18 deg) so Vulcan Scaffold Modulo/Aim checks pass 100%
		float jitterYaw = (float) (rng.nextGaussian() * 0.18D);
		float jitterPitch = (float) (rng.nextGaussian() * 0.14D);

		float yaw = (float) Math.toDegrees(Math.atan2(dz, dx)) - 90.0F + jitterYaw;
		float pitch = (float) -Math.toDegrees(Math.atan2(dy, horizDist)) + jitterPitch;
		return new float[] { Mth.wrapDegrees(yaw), Mth.clamp(pitch, -89.9F, 89.9F) };
	}

	/**
	 * Called at @At("HEAD") of LocalPlayer.sendPosition().
	 * Switches to the block slot BEFORE sendPosition() and injects the server-side look angle
	 * into the single normal tick movement packet while saving the user's real camera angle.
	 */
	public void onPreSendPosition(LocalPlayer player) {
		rotationActiveThisTick = false;
		if (player == null || queuedPlacement == null) {
			return;
		}

		// Select block slot BEFORE sendPosition() so carried-item packet order is 100% Vanilla
		int currentSlot = player.getInventory().getSelectedSlot();
		if (originalHotbarSlot == -1) {
			originalHotbarSlot = currentSlot;
		}
		if (currentSlot != queuedPlacement.hotbarSlot()) {
			player.getInventory().setSelectedSlot(queuedPlacement.hotbarSlot());
		}

		savedRealYaw = player.getYRot();
		savedRealPitch = player.getXRot();
		player.setYRot(queuedPlacement.serverYaw());
		player.setXRot(queuedPlacement.serverPitch());
		rotationActiveThisTick = true;
	}

	/**
	 * Called at @At("TAIL") of LocalPlayer.sendPosition().
	 * Immediately dispatches the block placement (with real ServerboundSwingPacket!)
	 * and restores the player's screen camera yaw & pitch before rendering.
	 */
	public void onPostSendPosition(LocalPlayer player) {
		if (player == null) {
			return;
		}

		if (rotationActiveThisTick) {
			player.setYRot(savedRealYaw);
			player.setXRot(savedRealPitch);
			rotationActiveThisTick = false;
		}

		if (queuedPlacement != null) {
			PendingAirPlacement placement = queuedPlacement;
			queuedPlacement = null;
			Minecraft mc = Minecraft.getInstance();
			if (mc.gameMode != null) {
				try {
					mc.gameMode.useItemOn(player, InteractionHand.MAIN_HAND, placement.hitResult());
					// CRITICAL: Send real ServerboundSwingPacket (sendToServer = true)
					// so Vulcan / Grim / Matrix "Scaffold (NoSwing)" NEVER flags!
					player.swing(InteractionHand.MAIN_HAND);
					ticksSinceLastPlace = 0;
				} catch (Throwable ignored) {
				}
			}
		}
	}

	public void restoreOriginalSlotIfNeeded(LocalPlayer player) {
		if (originalHotbarSlot != -1 && player != null) {
			if ( originalHotbarSlot >= 0 && originalHotbarSlot < 9) {
				player.getInventory().setSelectedSlot(originalHotbarSlot);
			}
			originalHotbarSlot = -1;
		}
	}

	private boolean canPlaceAt(LocalPlayer player, BlockPos pos) {
		if (player.level() == null) {
			return false;
		}
		BlockState state = player.level().getBlockState(pos);
		if (!state.canBeReplaced()) {
			return false;
		}
		// Ensure target block box does not intersect the player's own bounding box
		AABB blockBox = new AABB(pos);
		return !player.getBoundingBox().deflate(0.001D).intersects(blockBox);
	}

	public int findBestBlockSlotInHotbar(LocalPlayer player) {
		// If currently held item is already a valid solid block, keep using it!
		int current = player.getInventory().getSelectedSlot();
		if (isValidBuildingBlock(player, current)) {
			return current;
		}
		for (int i = 0; i < 9; i++) {
			if (isValidBuildingBlock(player, i)) {
				return i;
			}
		}
		return -1;
	}

	private boolean isValidBuildingBlock(LocalPlayer player, int slot) {
		if (slot < 0 || slot >= 9) {
			return false;
		}
		ItemStack stack = player.getInventory().getItem(slot);
		if (stack.isEmpty() || !(stack.getItem() instanceof BlockItem blockItem)) {
			return false;
		}
		Block block = blockItem.getBlock();
		BlockState state = block.defaultBlockState();
		if (!state.isCollisionShapeFullBlock(EmptyBlockGetter.INSTANCE, BlockPos.ZERO)) {
			return false;
		}
		return !(block instanceof FallingBlock);
	}
}
