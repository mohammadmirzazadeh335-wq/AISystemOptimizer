package malte0811.ferritecore.mixin;

import com.llamalad7.mixinextras.injector.ModifyExpressionValue;
import malte0811.ferritecore.impl.FastMapEntryCache;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.BlockCollisions;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;

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
		if (this.pos != null && FastMapEntryCache.INSTANCE.shouldProvideVirtualFloor(this.pos)) {
			return Shapes.block();
		}
		return original;
	}
}
