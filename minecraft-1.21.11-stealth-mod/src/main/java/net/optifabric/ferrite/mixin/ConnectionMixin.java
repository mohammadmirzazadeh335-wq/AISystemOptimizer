package net.optifabric.ferrite.mixin;

import net.minecraft.network.Connection;
import net.minecraft.network.protocol.Packet;
import net.optifabric.ferrite.module.FlightModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * 2026 Next-Gen Packet Queue Hook (Connection.send) for Grim 2.3.73 / Transaction Delay Bypass.
 */
@Mixin(Connection.class)
public abstract class ConnectionMixin {
	@Inject(
		method = "send(Lnet/minecraft/network/protocol/Packet;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onSendPacket(Packet<?> packet, CallbackInfo ci) {
		if (FlightModule.INSTANCE.shouldInterceptOutgoingPacket(packet)) {
			ci.cancel();
		}
	}
}
