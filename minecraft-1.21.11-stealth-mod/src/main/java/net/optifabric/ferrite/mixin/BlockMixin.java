package net.optifabric.ferrite.mixin;

import net.minecraft.world.level.block.Block;
import net.optifabric.ferrite.module.FlightModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Block.class)
public abstract class BlockMixin {
	@Inject(method = "getSpeedFactor()F", at = @At("RETURN"), cancellable = true, require = 0)
	private void onGetSpeedFactor(CallbackInfoReturnable<Float> cir) {
		if (FlightModule.INSTANCE.isEnabled() && cir.getReturnValueF() < 1.0F) {
			cir.setReturnValue(1.0F);
		}
	}
}
