package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import net.minecraft.client.Camera;
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
		if (BakedQuadDeduplicator.INSTANCE.isEnabled()) {
			cir.setReturnValue(false);
		}
	}
}
