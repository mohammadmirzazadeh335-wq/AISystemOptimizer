package net.optifabric.ferrite.mixin;

import net.minecraft.client.renderer.entity.EntityRenderer;
import net.minecraft.client.renderer.entity.state.EntityRenderState;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(EntityRenderer.class)
public abstract class EntityRendererMixin<T extends Entity, S extends EntityRenderState> {
	@Inject(
		method = "affectedByCulling(Lnet/minecraft/world/entity/Entity;)Z",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onAffectedByCulling(T entity, CallbackInfoReturnable<Boolean> cir) {
		if (XRayModule.INSTANCE.shouldHighlightEntity(entity)) {
			cir.setReturnValue(false);
		}
	}

	@Inject(
		method = "getBlockLightLevel(Lnet/minecraft/world/entity/Entity;Lnet/minecraft/core/BlockPos;)I",
		at = @At("RETURN"),
		cancellable = true,
		require = 0
	)
	private void onGetBlockLightLevel(T entity, BlockPos pos, CallbackInfoReturnable<Integer> cir) {
		if (XRayModule.INSTANCE.shouldHighlightEntity(entity)) {
			cir.setReturnValue(15);
		}
	}

	@Inject(
		method = "extractRenderState(Lnet/minecraft/world/entity/Entity;Lnet/minecraft/client/renderer/entity/state/EntityRenderState;F)V",
		at = @At("TAIL")
	)
	private void onExtractRenderState(T entity, S state, float tickProgress, CallbackInfo ci) {
		if (XRayModule.INSTANCE.shouldHighlightEntity(entity)) {
			state.outlineColor = XRayModule.INSTANCE.getEntityOutlineColor(entity);
		}
	}
}
