package net.optifabric.ferrite.mixin;

import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.Entity;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Minecraft.class)
public abstract class MinecraftMixin {
	@Inject(
		method = "shouldEntityAppearGlowing(Lnet/minecraft/world/entity/Entity;)Z",
		at = @At("HEAD"),
		cancellable = true
	)
	private void onShouldEntityAppearGlowing(Entity entity, CallbackInfoReturnable<Boolean> cir) {
		if (XRayModule.INSTANCE.shouldHighlightEntity(entity)) {
			cir.setReturnValue(true);
		}
	}

	@Inject(method = "allowsTelemetry()Z", at = @At("HEAD"), cancellable = true)
	private void onAllowsTelemetry(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}

	@Inject(method = "extraTelemetryAvailable()Z", at = @At("HEAD"), cancellable = true)
	private void onExtraTelemetryAvailable(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}
}
