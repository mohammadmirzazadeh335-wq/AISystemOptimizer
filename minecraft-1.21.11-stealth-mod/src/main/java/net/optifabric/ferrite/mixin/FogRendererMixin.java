package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.sugar.Local;
import net.minecraft.client.Camera;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.fog.FogData;
import net.minecraft.client.renderer.fog.FogRenderer;
import net.optifabric.ferrite.module.XRayModule;
import org.joml.Vector4f;
import org.objectweb.asm.Opcodes;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(FogRenderer.class)
public class FogRendererMixin {
	@Inject(
		method = "setupFog(Lnet/minecraft/client/Camera;ILnet/minecraft/client/DeltaTracker;FLnet/minecraft/client/multiplayer/ClientLevel;)Lorg/joml/Vector4f;",
		at = @At(
			value = "FIELD",
			target = "Lnet/minecraft/client/renderer/fog/FogData;renderDistanceEnd:F",
			opcode = Opcodes.PUTFIELD,
			shift = At.Shift.AFTER
		),
		require = 0
	)
	private void onSetupFog(
		Camera camera,
		int renderDistanceInChunks,
		DeltaTracker deltaTracker,
		float darkenWorldAmount,
		ClientLevel level,
		CallbackInfoReturnable<Vector4f> cir,
		@Local FogData fog
	) {
		if (!XRayModule.INSTANCE.isEnabled()) {
			return;
		}
		fog.renderDistanceStart = 1000000.0F;
		fog.renderDistanceEnd = 1000000.0F;
	}
}
