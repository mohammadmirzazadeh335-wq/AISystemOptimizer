package net.optifabric.ferrite.mixin;

import net.minecraft.client.Camera;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Pseudo
@Mixin(targets = "net.caffeinemc.mods.sodium.client.render.chunk.RenderSectionManager")
public class SodiumRenderSectionManagerMixin {
	@Inject(
		method = "shouldUseOcclusionCulling",
		at = @At("HEAD"),
		cancellable = true,
		require = 0,
		remap = false
	)
	private void onShouldUseOcclusionCulling(
		Camera camera,
		boolean spectator,
		CallbackInfoReturnable<Boolean> cir
	) {
		if (XRayModule.INSTANCE.isEnabled()) {
			cir.setReturnValue(false);
		}
	}
}
