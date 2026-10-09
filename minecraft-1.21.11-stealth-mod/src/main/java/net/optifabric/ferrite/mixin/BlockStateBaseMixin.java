package net.optifabric.ferrite.mixin;

import com.mojang.serialization.MapCodec;
import it.unimi.dsi.fastutil.objects.Reference2ObjectArrayMap;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockBehaviour.BlockStateBase;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateHolder;
import net.minecraft.world.level.block.state.properties.Property;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(BlockStateBase.class)
public abstract class BlockStateBaseMixin extends StateHolder<Block, BlockState> {
	private BlockStateBaseMixin(
		Block owner,
		Reference2ObjectArrayMap<Property<?>, Comparable<?>> propertyMap,
		MapCodec<BlockState> codec
	) {
		super(owner, propertyMap, codec);
	}

	@Inject(
		method = "getShadeBrightness(Lnet/minecraft/world/level/BlockGetter;Lnet/minecraft/core/BlockPos;)F",
		at = @At("RETURN"),
		cancellable = true,
		order = 980,
		require = 0
	)
	private void onGetShadeBrightness(
		BlockGetter blockGetter,
		BlockPos blockPos,
		CallbackInfoReturnable<Float> cir
	) {
		if (XRayModule.INSTANCE.isEnabled()) {
			cir.setReturnValue(1.0F);
		}
	}
}
