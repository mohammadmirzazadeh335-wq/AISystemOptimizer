package malte0811.ferritecore.mixin;

import com.mojang.blaze3d.vertex.PoseStack;
import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.blockentity.BlockEntityRenderDispatcher;
import net.minecraft.client.renderer.blockentity.state.BlockEntityRenderState;
import net.minecraft.client.renderer.state.CameraRenderState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(BlockEntityRenderDispatcher.class)
public class BlockEntityRenderDispatcherMixin {
	@Inject(
		method = "submit(Lnet/minecraft/client/renderer/blockentity/state/BlockEntityRenderState;Lcom/mojang/blaze3d/vertex/PoseStack;Lnet/minecraft/client/renderer/SubmitNodeCollector;Lnet/minecraft/client/renderer/state/CameraRenderState;)V",
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private <S extends BlockEntityRenderState> void onSubmit(
		S renderState,
		PoseStack matrices,
		SubmitNodeCollector queue,
		CameraRenderState cameraRenderState,
		CallbackInfo ci
	) {
		if (BakedQuadDeduplicator.INSTANCE.shouldHideBlockEntity(renderState)) {
			ci.cancel();
		}
	}
}
