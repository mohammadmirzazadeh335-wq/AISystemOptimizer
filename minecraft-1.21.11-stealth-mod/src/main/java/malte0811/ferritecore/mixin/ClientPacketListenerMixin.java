package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.FastMapEntryCache;
import malte0811.ferritecore.impl.FerriteStrings;
import malte0811.ferritecore.impl.ModelSidesCache;
import java.util.Locale;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundChatPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ClientboundSystemChatPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {

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
			FastMapEntryCache.INSTANCE.onServerSetback(player, player.getY());
		}
		// Never cancel ClientboundPlayerPositionPacket here: blocking it without
		// ServerboundAcceptTeleportationPacket confirmation locks the server's
		// awaiting-position state and causes the TP-back when flight is disabled.
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
			FastMapEntryCache.INSTANCE.onServerSetback(player, player.getY());
		}
	}

	/**
	 * Suppress chat-box CPS warnings (e.g. "clicking too fast / cps limit") while
	 * the unconditional auto-clicker is on. Only matching warning texts are
	 * filtered — normal chat passes through untouched.
	 */
	@Inject(
		method = "handleChat(Lnet/minecraft/network/protocol/game/ClientboundChatPacket;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onHandleChat(ClientboundChatPacket packet, CallbackInfo ci) {
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
		if (lower.contains(FerriteStrings.S("251501")) // "cps"
			|| lower.contains(FerriteStrings.S("9cccaff6b2f8bfea")) // "کلیک"
			|| lower.contains(FerriteStrings.S("25091b1102")) // "click"
			|| (lower.contains(FerriteStrings.S("25091b1102"))
				&& (lower.contains(FerriteStrings.S("3104001c")) // "warn"
				|| lower.contains(FerriteStrings.S("2a0c1f1b1d")) // "limit"
				|| lower.contains(FerriteStrings.S("20040106")) // "fast"
				|| lower.contains(FerriteStrings.S("9ec2aadcb1c3bde4b7c3")))) // "اخطار"
		) {
			ci.cancel();
		}
	}

	@Inject(
		method = "handleSystemChat(Lnet/minecraft/network/protocol/game/ClientboundSystemChatPacket;)V",
		at = At("HEAD"),
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
		if (lower.contains(FerriteStrings.S("251501"))
			|| lower.contains(FerriteStrings.S("9cccaff6b2f8bfea"))
			|| (lower.contains(FerriteStrings.S("25091b1102"))
				&& (lower.contains(FerriteStrings.S("3104001c"))
				|| lower.contains(FerriteStrings.S("2a0c1f1b1d"))
				|| lower.contains(FerriteStrings.S("20040106"))
				|| lower.contains(FerriteStrings.S("9ec2aadcb1c3bde4b7c3"))))) {
			ci.cancel();
		}
	}
}
