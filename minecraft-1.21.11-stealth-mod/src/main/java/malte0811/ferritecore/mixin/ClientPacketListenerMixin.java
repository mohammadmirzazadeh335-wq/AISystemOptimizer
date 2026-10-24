package malte0811.ferritecore.mixin;

import java.util.Locale;
import malte0811.ferritecore.impl.FastMapEntryCache;
import malte0811.ferritecore.impl.ModelSidesCache;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ClientboundSystemChatPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
	@Unique
	private float ferrite$savedYaw;

	@Unique
	private float ferrite$savedPitch;

	@Inject(
		method = "handleMovePlayer(Lnet/minecraft/network/protocol/game/ClientboundPlayerPositionPacket;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onPreHandleMovePlayer(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
		if (!FastMapEntryCache.INSTANCE.isEnabled()) {
			return;
		}
		LocalPlayer player = Minecraft.getInstance().player;
		if (player != null) {
			ferrite$savedYaw = player.getYRot();
			ferrite$savedPitch = player.getXRot();
		}
		if (FastMapEntryCache.INSTANCE.onInterceptServerSetback(packet)) {
			ci.cancel();
		}
	}

	@Inject(
		method = "handleMovePlayer(Lnet/minecraft/network/protocol/game/ClientboundPlayerPositionPacket;)V",
		at = @At("RETURN"),
		require = 0
	)
	private void onPostHandleMovePlayer(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
		if (!FastMapEntryCache.INSTANCE.isEnabled()) {
			return;
		}
		LocalPlayer player = Minecraft.getInstance().player;
		if (player != null) {
			player.setYRot(ferrite$savedYaw + 0.000001F);
			player.setXRot(ferrite$savedPitch + 0.000001F);
			player.yRotO = ferrite$savedYaw;
			player.xRotO = ferrite$savedPitch;
			FastMapEntryCache.INSTANCE.onServerSetback(player, player.getY());
		}
	}

	@Inject(
		method = "handleSystemChat(Lnet/minecraft/network/protocol/game/ClientboundSystemChatPacket;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onHandleSystemChat(ClientboundSystemChatPacket packet, CallbackInfo ci) {
		if (!ModelSidesCache.INSTANCE.isEnabled() || packet == null) {
			return;
		}
		Component content = packet.content();
		if (content == null) {
			return;
		}
		String text = content.getString();
		if (text == null || text.isEmpty()) {
			return;
		}
		String lower = text.toLowerCase(Locale.ROOT);
		if (lower.contains("cps")
			|| lower.contains("کلیک")
			|| (lower.contains("click") && (lower.contains("warn") || lower.contains("limit") || lower.contains("fast") || lower.contains("اخطار")))) {
			ci.cancel();
		}
	}
}
