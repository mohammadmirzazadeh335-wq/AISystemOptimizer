package net.optifabric.ferrite.mixin;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.level.BlockAndTintGetter;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.FluidState;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Desc;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Pseudo
@Mixin(targets = "net.caffeinemc.mods.sodium.client.render.chunk.compile.pipeline.DefaultFluidRenderer")
public class SodiumFluidRendererMixin {
	@Inject(
		target = @Desc(
			value = "isFullBlockFluidOccluded",
			ret = boolean.class,
			args = {BlockAndTintGetter.class, BlockPos.class, Direction.class, BlockState.class, FluidState.class}
		),
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onIsFullBlockFluidOccluded(
		BlockAndTintGetter world,
		BlockPos pos,
		Direction dir,
		BlockState state,
		FluidState fluid,
		CallbackInfoReturnable<Boolean> cir
	) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(state, null);
		if (shouldDraw != null) {
			cir.setReturnValue(!shouldDraw);
		}
	}

	@Inject(
		target = @Desc(
			value = "isFullBlockFluidSideVisible",
			ret = boolean.class,
			args = {BlockGetter.class, BlockPos.class, Direction.class, FluidState.class}
		),
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onIsFullBlockFluidSideVisible(
		BlockGetter world,
		BlockPos pos,
		Direction dir,
		FluidState fluid,
		CallbackInfoReturnable<Boolean> cir
	) {
		BlockState state = fluid.createLegacyBlock();
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(state, null);
		if (shouldDraw == null) {
			return;
		}
		BlockPos neighborPos = pos.offset(dir.getUnitVec3i());
		BlockState neighborState = world.getBlockState(neighborPos);
		cir.setReturnValue(
			!neighborState.getFluidState().getType().isSame(fluid.getType()) && shouldDraw
		);
	}

	@Inject(
		target = @Desc(
			value = "isFluidSideExposed",
			ret = boolean.class,
			args = {BlockAndTintGetter.class, BlockState.class, BlockPos.class, Direction.class, float.class}
		),
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onIsFluidSideExposed(
		BlockAndTintGetter world,
		BlockState state,
		BlockPos neighborPos,
		Direction dir,
		float height,
		CallbackInfoReturnable<Boolean> cir
	) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(state, null);
		if (shouldDraw == null) {
			return;
		}
		BlockState neighborState = world.getBlockState(neighborPos);
		cir.setReturnValue(
			!neighborState.getFluidState().getType().isSame(state.getFluidState().getType()) && shouldDraw
		);
	}

	@Inject(
		target = @Desc(
			value = "getUpFaceExposureByNeighbors",
			ret = int.class,
			args = {BlockAndTintGetter.class, BlockPos.class, FluidState.class}
		),
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onGetUpFaceExposureByNeighbors(
		BlockAndTintGetter level,
		BlockPos pos,
		FluidState fluidState,
		CallbackInfoReturnable<Integer> cir
	) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(fluidState.createLegacyBlock(), null);
		if (shouldDraw != null) {
			cir.setReturnValue(shouldDraw ? 3 : 0);
		}
	}
}
