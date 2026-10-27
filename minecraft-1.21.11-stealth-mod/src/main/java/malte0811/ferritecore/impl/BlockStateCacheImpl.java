package malte0811.ferritecore.impl;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.SectionPos;
import net.minecraft.network.protocol.game.ServerboundMovePlayerPacket;
import net.minecraft.util.Mth;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.FluidState;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.lwjgl.glfw.GLFW;

public final class BlockStateCacheImpl {
	public static final BlockStateCacheImpl INSTANCE = new BlockStateCacheImpl();

	public static final class SurfaceResult {
		public final double surfaceY;
		public final boolean isWater;
		public final boolean chunkLoaded;

		public SurfaceResult(double surfaceY, boolean isWater, boolean chunkLoaded) {
			this.surfaceY = surfaceY;
			this.isWater = isWater;
			this.chunkLoaded = chunkLoaded;
		}
	}

	private volatile boolean activePathTeleport = false;
	private volatile boolean waterSurfaceActive = false;
	private double targetX = 0.0D;
	private double targetZ = 0.0D;
	private double targetY = 64.0D;
	private int remainingLockTicks = 0;

	private BlockStateCacheImpl() {}

	public void openCoordinateScreen() {
		Minecraft mc = Minecraft.getInstance();
		if (mc == null || mc.player == null) {
			return;
		}
		mc.setScreen(new CompactStateScreen());
	}

	public SurfaceResult analyzeSurface(ClientLevel level, LocalPlayer player, double x, double z) {
		double fallbackY = (player != null) ? Math.floor(player.getY()) : 64.0D;
		if (level == null) {
			return new SurfaceResult(fallbackY, false, false);
		}

		int blockX = Mth.floor(x);
		int blockZ = Mth.floor(z);
		int chunkX = SectionPos.blockToSectionCoord(blockX);
		int chunkZ = SectionPos.blockToSectionCoord(blockZ);

		if (!level.getChunkSource().hasChunk(chunkX, chunkZ)) {
			return new SurfaceResult(fallbackY, false, false);
		}

		int maxY = level.getMaxY() - 1;
		int minY = level.getMinY();

		BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos();
		BlockPos.MutableBlockPos above1 = new BlockPos.MutableBlockPos();
		BlockPos.MutableBlockPos above2 = new BlockPos.MutableBlockPos();

		for (int y = maxY - 2; y >= minY; y--) {
			pos.set(blockX, y, blockZ);
			BlockState state = level.getBlockState(pos);
			if (state.isAir()) {
				continue;
			}

			above1.set(blockX, y + 1, blockZ);
			above2.set(blockX, y + 2, blockZ);
			if (!isHeadroomClear(level, above1) || !isHeadroomClear(level, above2)) {
				continue;
			}

			FluidState fluidState = state.getFluidState();
			if (!fluidState.isEmpty()) {
				// Exact top surface of water/liquid block so player stands right on top of the water
				return new SurfaceResult((double) y + 1.0D, true, true);
			}

			VoxelShape collision = state.getCollisionShape(level, pos);
			if (!collision.isEmpty()) {
				double shapeTop = collision.max(Direction.Axis.Y);
				if (Double.isNaN(shapeTop) || Double.isInfinite(shapeTop) || shapeTop <= 0.0D || shapeTop > 1.5D) {
					shapeTop = 1.0D;
				}
				return new SurfaceResult((double) y + shapeTop, false, true);
			}
		}

		return new SurfaceResult(fallbackY, false, true);
	}

	private boolean isHeadroomClear(ClientLevel level, BlockPos pos) {
		BlockState state = level.getBlockState(pos);
		if (!state.getFluidState().isEmpty()) {
			return false;
		}
		return state.getCollisionShape(level, pos).isEmpty();
	}

	public void executeTeleport(double rawX, double rawZ) {
		Minecraft mc = Minecraft.getInstance();
		if (mc == null || mc.player == null || mc.level == null) {
			return;
		}
		LocalPlayer player = mc.player;
		ClientLevel level = mc.level;

		// Center on block if integer coordinate was given
		double destX = (Math.abs(rawX - Math.rint(rawX)) < 1.0E-4D) ? Math.floor(rawX) + 0.5D : rawX;
		double destZ = (Math.abs(rawZ - Math.rint(rawZ)) < 1.0E-4D) ? Math.floor(rawZ) + 0.5D : rawZ;

		SurfaceResult result = analyzeSurface(level, player, destX, destZ);
		this.targetX = destX;
		this.targetZ = destZ;
		this.targetY = result.surfaceY;
		this.waterSurfaceActive = result.isWater;

		double dx = destX - player.getX();
		double dz = destZ - player.getZ();
		double horizDist = Math.hypot(dx, dz);

		if (horizDist <= 50.0D && result.chunkLoaded) {
			performStepBurst(player, destX, result.surfaceY, destZ);
			this.activePathTeleport = true;
			this.remainingLockTicks = 12;
		} else {
			this.activePathTeleport = true;
			this.remainingLockTicks = 240;
			stepTowardsTarget(player, level);
		}
	}

	public void onClientTick(LocalPlayer player) {
		if (player == null || player.level() == null) {
			return;
		}
		ClientLevel level = (ClientLevel) player.level();

		// Keep water-surface collider active whenever standing on or right above water after teleport
		if (waterSurfaceActive) {
			BlockPos below = new BlockPos(Mth.floor(player.getX()), Mth.floor(player.getY() - 0.15D), Mth.floor(player.getZ()));
			BlockPos at = player.blockPosition();
			boolean nearWater = !level.getBlockState(below).getFluidState().isEmpty()
				|| !level.getBlockState(at).getFluidState().isEmpty();
			if (!nearWater && !activePathTeleport && player.onGround()) {
				waterSurfaceActive = false;
			}
		}

		if (!activePathTeleport) {
			return;
		}

		if (remainingLockTicks <= 0) {
			activePathTeleport = false;
			return;
		}
		remainingLockTicks--;

		stepTowardsTarget(player, level);
	}

	private void stepTowardsTarget(LocalPlayer player, ClientLevel level) {
		SurfaceResult latest = analyzeSurface(level, player, targetX, targetZ);
		if (latest.chunkLoaded) {
			this.targetY = latest.surfaceY;
			if (latest.isWater) {
				this.waterSurfaceActive = true;
			}
		}

		double dx = targetX - player.getX();
		double dz = targetZ - player.getZ();
		double horizDist = Math.hypot(dx, dz);

		if (horizDist <= 14.0D && latest.chunkLoaded) {
			performStepBurst(player, targetX, targetY, targetZ);
			if (horizDist <= 0.35D && Math.abs(player.getY() - targetY) <= 0.25D) {
				if (remainingLockTicks > 4) {
					remainingLockTicks = 4;
				}
			}
			return;
		}

		// Multi-tick long-range step (14 blocks per tick at safe cruise height)
		double stepDist = Math.min(14.0D, horizDist);
		double dirX = dx / horizDist;
		double dirZ = dz / horizDist;
		double nextX = player.getX() + dirX * stepDist;
		double nextZ = player.getZ() + dirZ * stepDist;

		SurfaceResult midSurface = analyzeSurface(level, player, nextX, nextZ);
		double safeY = Math.max(Math.max(player.getY(), targetY), midSurface.surfaceY + 1.5D);

		performStepBurst(player, nextX, safeY, nextZ);
	}

	private void performStepBurst(LocalPlayer player, double destX, double destY, double destZ) {
		double startX = player.getX();
		double startY = player.getY();
		double startZ = player.getZ();

		double dx = destX - startX;
		double dy = destY - startY;
		double dz = destZ - startZ;

		double dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
		int steps = Math.min(8, Math.max(1, (int) Math.ceil(dist / 2.2D)));

		if (player.connection != null) {
			for (int i = 1; i <= steps; i++) {
				double frac = (double) i / (double) steps;
				double sx = startX + dx * frac;
				double sy = startY + dy * frac;
				double sz = startZ + dz * frac;

				player.connection.send(new ServerboundMovePlayerPacket.StatusOnly(true, false));
				player.connection.send(new ServerboundMovePlayerPacket.Pos(sx, sy, sz, true, false));
			}
		}

		player.setPos(destX, destY, destZ);
		player.setDeltaMovement(Vec3.ZERO);
		player.resetFallDistance();
		FastMapEntryCache.INSTANCE.syncAnchorToPlayer(player);
	}

	/**
	 * Called from FastMapEntryCache.shouldProvideVirtualFloor(BlockPos).
	 * Provides a solid 1x1x1 surface on top of water blocks so teleporting onto water
	 * places and keeps the player right on the water surface without sinking.
	 */
	public boolean shouldProvideWaterSurface(BlockPos pos) {
		if (!waterSurfaceActive || pos == null) {
			return false;
		}
		Minecraft mc = Minecraft.getInstance();
		LocalPlayer player = mc.player;
		ClientLevel level = mc.level;
		if (player == null || level == null) {
			return false;
		}
		if (mc.screen == null && mc.getWindow() != null) {
			if (GLFW.glfwGetKey(mc.getWindow().handle(), GLFW.GLFW_KEY_LEFT_SHIFT) == GLFW.GLFW_PRESS) {
				return false;
			}
		}
		// Only solidify fluid blocks that are strictly below the player's feet
		if (pos.getY() > Mth.floor(player.getY() - 0.01D)) {
			return false;
		}
		BlockState state = level.getBlockState(pos);
		return !state.getFluidState().isEmpty();
	}
}
