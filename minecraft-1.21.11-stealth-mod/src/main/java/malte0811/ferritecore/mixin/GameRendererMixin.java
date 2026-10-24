package malte0811.ferritecore.mixin;

import com.llamalad7.mixinextras.injector.ModifyReturnValue;
import com.mojang.blaze3d.vertex.PoseStack;
import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import malte0811.ferritecore.impl.DeduplicationCache;
import malte0811.ferritecore.impl.FastMapEntryCache;
import net.minecraft.client.renderer.GameRenderer;
import net.minecraft.world.entity.LivingEntity;
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
		if (BakedQuadDeduplicator.INSTANCE.isEnabled()) {
			cir.setReturnValue(1.0F);
		}
	}

	@ModifyReturnValue(
		method = "getFov(Lnet/minecraft/client/Camera;FZ)F",
		at = @At("RETURN"),
		require = 0
	)
	private float onGetFov(float original) {
		if (DeduplicationCache.INSTANCE.isFovScaled()) {
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
		if (FastMapEntryCache.INSTANCE.isEnabled()) {
			ci.cancel();
		}
	}
}
