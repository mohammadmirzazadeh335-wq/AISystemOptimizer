package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.blaze3d.vertex.VertexConsumer;
import java.util.List;
import net.minecraft.client.renderer.block.ModelBlockRenderer;
import net.minecraft.client.renderer.block.model.BakedQuad;
import net.minecraft.client.renderer.block.model.BlockModelPart;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.level.BlockAndTintGetter;
import net.minecraft.world.level.block.state.BlockState;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;

@Mixin(ModelBlockRenderer.class)
public abstract class ModelBlockRendererMixin {
	@WrapOperation(
		method = "shouldRenderFace(Lnet/minecraft/world/level/BlockAndTintGetter;Lnet/minecraft/world/level/block/state/BlockState;ZLnet/minecraft/core/Direction;Lnet/minecraft/core/BlockPos;)Z",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/world/level/block/Block;shouldRenderFace(Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/core/Direction;)Z"
		),
		require = 0
	)
	private static boolean onShouldRenderFace(
		BlockState state,
		BlockState otherState,
		Direction side,
		Operation<Boolean> original,
		BlockAndTintGetter world,
		BlockState stateFromOuter,
		boolean cull,
		Direction sideFromOuter,
		BlockPos neighborPos
	) {
		BlockPos pos = neighborPos.relative(side.getOpposite());
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(state, pos);
		if (shouldDraw != null) {
			return shouldDraw;
		}
		return original.call(state, otherState, side);
	}

	@WrapOperation(
		method = {
			"tesselateWithoutAO(Lnet/minecraft/world/level/BlockAndTintGetter;Ljava/util/List;Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/core/BlockPos;Lcom/mojang/blaze3d/vertex/PoseStack;Lcom/mojang/blaze3d/vertex/VertexConsumer;ZI)V",
			"tesselateWithAO(Lnet/minecraft/world/level/BlockAndTintGetter;Ljava/util/List;Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/core/BlockPos;Lcom/mojang/blaze3d/vertex/PoseStack;Lcom/mojang/blaze3d/vertex/VertexConsumer;ZI)V"
		},
		at = @At(
			value = "INVOKE",
			target = "Ljava/util/List;isEmpty()Z",
			ordinal = 1
		),
		require = 0
	)
	private boolean onCheckQuadListEmpty(
		List<BakedQuad> instance,
		Operation<Boolean> original,
		BlockAndTintGetter world,
		List<BlockModelPart> list,
		BlockState state,
		BlockPos pos,
		PoseStack poseStack,
		VertexConsumer vertexConsumer,
		boolean cull,
		int light
	) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(state, pos);
		if (Boolean.FALSE.equals(shouldDraw)) {
			return true;
		}
		return original.call(instance);
	}
}
