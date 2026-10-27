package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.FastMapEntryCache;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.Packet;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Connection.class)
public abstract class ConnectionMixin {
	@Inject(
		method = "send(Lnet/minecraft/network/protocol/Packet;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onSendPacket(Packet<?> packet, CallbackInfo ci) {
		if (FastMapEntryCache.INSTANCE.shouldInterceptOutgoingPacket(packet)) {
			ci.cancel();
		}
	}
}
