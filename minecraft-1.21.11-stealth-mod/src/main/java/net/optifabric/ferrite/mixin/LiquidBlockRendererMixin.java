package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.mojang.blaze3d.vertex.VertexConsumer;
import net.minecraft.client.renderer.block.LiquidBlockRenderer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.level.BlockAndTintGetter;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.FluidState;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;

@Mixin(LiquidBlockRenderer.class)
public class LiquidBlockRendererMixin {
	@WrapOperation(
		method = "tesselate(Lnet/minecraft/world/level/BlockAndTintGetter;Lnet/minecraft/core/BlockPos;Lcom/mojang/blaze3d/vertex/VertexConsumer;Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/material/FluidState;)V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/renderer/block/LiquidBlockRenderer;isFaceOccludedByNeighbor(Lnet/minecraft/core/Direction;FLnet/minecraft/world/level/block/state/BlockState;)Z"
		),
		require = 0
	)
	private boolean onIsFaceOccludedByNeighbor(
		Direction side,
		float height,
		BlockState neighborState,
		Operation<Boolean> original,
		BlockAndTintGetter world,
		BlockPos pos,
		VertexConsumer vertexConsumer,
		BlockState blockState,
		FluidState fluidState
	) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(blockState, null);
		if (shouldDraw != null) {
			return !shouldDraw;
		}
		return original.call(side, height, neighborState);
	}
}
