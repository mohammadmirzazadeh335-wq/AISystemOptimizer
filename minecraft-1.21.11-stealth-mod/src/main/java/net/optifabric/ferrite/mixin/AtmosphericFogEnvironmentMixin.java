package net.optifabric.ferrite.mixin;

import net.minecraft.client.Camera;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.fog.FogData;
import net.minecraft.client.renderer.fog.environment.AtmosphericFogEnvironment;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(AtmosphericFogEnvironment.class)
public class AtmosphericFogEnvironmentMixin {
	@Inject(method = "setupFog", at = @At("TAIL"), require = 0)
	private void onSetupFog(
		FogData data,
		Camera camera,
		ClientLevel world,
		float viewDistance,
		DeltaTracker tickCounter,
		CallbackInfo ci
	) {
		if (!XRayModule.INSTANCE.isEnabled()) {
			return;
		}
		data.environmentalStart = 1000000.0F;
		data.environmentalEnd = 1000000.0F;
	}
}
