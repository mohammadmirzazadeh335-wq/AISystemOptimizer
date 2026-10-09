package net.optifabric.ferrite.mixin;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.level.block.state.BlockState;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Pseudo
@Mixin(
	targets = "net.fabricmc.fabric.impl.client.indigo.renderer.render.BlockRenderInfo",
	remap = false
)
public abstract class IndigoBlockRenderInfoMixin {
	@Shadow
	public BlockPos blockPos;

	@Shadow
	public BlockState blockState;

	@Inject(
		method = "shouldDrawSide",
		at = @At("HEAD"),
		require = 0,
		cancellable = true
	)
	private void onShouldDrawSide(Direction face, CallbackInfoReturnable<Boolean> cir) {
		Boolean shouldDraw = XRayModule.INSTANCE.shouldDrawSide(blockState, blockPos);
		if (shouldDraw != null) {
			cir.setReturnValue(shouldDraw);
		}
	}
}
