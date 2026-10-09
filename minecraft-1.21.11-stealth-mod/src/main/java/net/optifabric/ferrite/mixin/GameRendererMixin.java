package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.ModifyReturnValue;
import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.world.entity.LivingEntity;
import net.optifabric.ferrite.core.StealthController;
import net.optifabric.ferrite.module.FlightModule;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(GameRenderer.class)
public abstract class GameRendererMixin {
	@Inject(
		method = "getNightVisionScale(Lnet/minecraft/world/entity/LivingEntity;F)F",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private static void onGetNightVisionScale(
		LivingEntity entity,
		float tickDelta,
		CallbackInfoReturnable<Float> cir
	) {
		if (XRayModule.INSTANCE.isEnabled()) {
			cir.setReturnValue(1.0F);
		}
	}

	@ModifyReturnValue(
		method = "getFov(Lnet/minecraft/client/Camera;FZ)F",
		at = @At("RETURN"),
		require = 0
	)
	private float onGetFov(float original) {
		if (StealthController.INSTANCE.isZoomActive()) {
			return original * 0.25F;
		}
		return original;
	}

	@Inject(
		method = "bobHurt(Lcom/mojang/blaze3d/vertex/PoseStack;F)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onBobHurt(PoseStack matrices, float tickDelta, CallbackInfo ci) {
		if (FlightModule.INSTANCE.isEnabled()) {
			ci.cancel();
		}
	}
}
