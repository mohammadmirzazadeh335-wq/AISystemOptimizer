package net.optifabric.ferrite.mixin;

import net.minecraft.client.telemetry.ClientTelemetryManager;
import net.minecraft.client.telemetry.TelemetryEventSender;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(ClientTelemetryManager.class)
public class ClientTelemetryManagerMixin {
	@Inject(
		method = "getOutsideSessionSender()Lnet/minecraft/client/telemetry/TelemetryEventSender;",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onGetOutsideSessionSender(CallbackInfoReturnable<TelemetryEventSender> cir) {
		cir.setReturnValue(TelemetryEventSender.DISABLED);
	}
}
