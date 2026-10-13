package net.optifabric.ferrite.mixin;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.optifabric.ferrite.module.FlightModule;
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
		require = 0
	)
	private void onPreHandleMovePlayer(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
		if (!FlightModule.INSTANCE.isEnabled()) {
			return;
		}
		LocalPlayer player = Minecraft.getInstance().player;
		if (player != null) {
			ferrite$savedYaw = player.getYRot();
			ferrite$savedPitch = player.getXRot();
		}
	}

	@Inject(
		method = "handleMovePlayer(Lnet/minecraft/network/protocol/game/ClientboundPlayerPositionPacket;)V",
		at = @At("RETURN"),
		require = 0
	)
	private void onPostHandleMovePlayer(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
		if (!FlightModule.INSTANCE.isEnabled()) {
			return;
		}
		LocalPlayer player = Minecraft.getInstance().player;
		if (player != null) {
			// Silent No-Rotate Setback: preserve player camera yaw & pitch so server setbacks don't jerk aim
			player.setYRot(ferrite$savedYaw);
			player.setXRot(ferrite$savedPitch);
			player.yRotO = ferrite$savedYaw;
			player.xRotO = ferrite$savedPitch;
			FlightModule.INSTANCE.onServerSetback(player, player.getY());
		}
	}
}
