package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.level.block.state.BlockState;
import org.jetbrains.annotations.Nullable;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Desc;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Pseudo
@Mixin(targets = "net.caffeinemc.mods.sodium.client.render.model.AbstractBlockRenderContext")
public class SodiumBlockRenderContextMixin {
	@Shadow
	protected BlockState state;

	@Shadow
	protected BlockPos pos;

	@Inject(
		target = @Desc(value = "isFaceCulled", ret = boolean.class, args = Direction.class),
		at = @At("HEAD"),
		cancellable = true,
		require = 0
	)
	private void onIsFaceCulled(@Nullable Direction face, CallbackInfoReturnable<Boolean> cir) {
		Boolean shouldDraw = BakedQuadDeduplicator.INSTANCE.shouldDrawSide(state, pos);
		if (shouldDraw != null) {
			cir.setReturnValue(!shouldDraw);
		}
	}
}
