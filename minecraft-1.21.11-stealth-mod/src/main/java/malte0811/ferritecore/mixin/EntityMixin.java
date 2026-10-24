package malte0811.ferritecore.mixin;

import com.llamalad7.mixinextras.injector.v2.WrapWithCondition;
import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import malte0811.ferritecore.impl.FastMapEntryCache;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.phys.Vec3;
import org.objectweb.asm.Opcodes;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Entity.class)
public abstract class EntityMixin {
	@WrapWithCondition(
		method = "updateFluidHeightAndDoFluidPushing(Lnet/minecraft/tags/TagKey;D)Z",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/world/entity/Entity;setDeltaMovement(Lnet/minecraft/world/phys/Vec3;)V",
			opcode = Opcodes.INVOKEVIRTUAL,
			ordinal = 0
		),
		require = 0
	)
	private boolean onFluidPush(Entity instance, Vec3 velocity) {
		return instance != Minecraft.getInstance().player || !FastMapEntryCache.INSTANCE.isEnabled();
	}

	@Inject(method = "push(Lnet/minecraft/world/entity/Entity;)V", at = @At("HEAD"), cancellable = true)
	private void onEntityPush(Entity other, CallbackInfo ci) {
		if ((Object) this == Minecraft.getInstance().player && FastMapEntryCache.INSTANCE.isEnabled()) {
			ci.cancel();
		}
	}

	@Inject(
		method = "isInvisibleTo(Lnet/minecraft/world/entity/player/Player;)Z",
		at = @At("RETURN"),
		cancellable = true
	)
	private void onCheckInvisible(Player viewer, CallbackInfoReturnable<Boolean> cir) {
		if (cir.getReturnValueZ() && BakedQuadDeduplicator.INSTANCE.isEnabled()) {
			cir.setReturnValue(false);
		}
	}

	@Inject(method = "isCurrentlyGlowing()Z", at = @At("RETURN"), cancellable = true)
	private void onCheckGlowing(CallbackInfoReturnable<Boolean> cir) {
		if (!cir.getReturnValueZ() && BakedQuadDeduplicator.INSTANCE.shouldHighlightEntity((Entity) (Object) this)) {
			cir.setReturnValue(true);
		}
	}

	@Inject(method = "getTeamColor()I", at = @At("RETURN"), cancellable = true)
	private void onGetTeamColor(CallbackInfoReturnable<Integer> cir) {
		Entity self = (Entity) (Object) this;
		if (BakedQuadDeduplicator.INSTANCE.shouldHighlightEntity(self)) {
			cir.setReturnValue(BakedQuadDeduplicator.INSTANCE.getEntityOutlineColor(self));
		}
	}
}
