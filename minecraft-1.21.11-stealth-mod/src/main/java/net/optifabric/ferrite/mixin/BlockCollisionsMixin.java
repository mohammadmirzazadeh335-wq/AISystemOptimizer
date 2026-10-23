package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.ModifyExpressionValue;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.BlockCollisions;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;
import net.optifabric.ferrite.module.FlightModule;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;

/**
 * 2026 Next-Gen Virtual Air-Collision Floor Hook (BlockCollisions.computeNext).
 *
 * Provides a full 1x1x1 VoxelShape (Shapes.block()) directly beneath the player's feet
 * during Flight so Vanilla's own Entity.collide() and LivingEntity.travel() walk/jump
 * on mid-air with 100% native physics without affecting crosshair raycasts or rendering.
 */
@Mixin(BlockCollisions.class)
public abstract class BlockCollisionsMixin {
	@Shadow
	@Final
	private BlockPos.MutableBlockPos pos;

	@ModifyExpressionValue(
		method = "computeNext()Ljava/lang/Object;",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/world/phys/shapes/CollisionContext;getCollisionShape(Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/CollisionGetter;Lnet/minecraft/core/BlockPos;)Lnet/minecraft/world/phys/shapes/VoxelShape;"
		),
		require = 0
	)
	private VoxelShape onGetCollisionShape(VoxelShape original) {
		if (this.pos != null && FlightModule.INSTANCE.shouldProvideVirtualFloor(this.pos)) {
			return Shapes.block();
		}
		return original;
	}
}
