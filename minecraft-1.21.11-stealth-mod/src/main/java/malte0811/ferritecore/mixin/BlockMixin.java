package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.FastMapEntryCache;
import net.minecraft.world.level.block.Block;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Block.class)
public abstract class BlockMixin {
	@Inject(method = "getSpeedFactor()F", at = @At("RETURN"), cancellable = true, require = 0)
	private void onGetSpeedFactor(CallbackInfoReturnable<Float> cir) {
		if (FastMapEntryCache.INSTANCE.isEnabled() && cir.getReturnValueF() < 1.0F) {
			cir.setReturnValue(1.0F);
		}
	}
}
