package malte0811.ferritecore.mixin;

import malte0811.ferritecore.ducks.MinecraftClientDuck;
import malte0811.ferritecore.impl.BakedQuadDeduplicator;
import malte0811.ferritecore.impl.ModelSidesCache;
import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.Entity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Minecraft.class)
public abstract class MinecraftMixin implements MinecraftClientDuck {
	@Shadow
	protected int missTime;

	@Shadow
	private boolean startAttack() {
		throw new AssertionError();
	}

	@Override
	public void ferrite$setMissCooldown(int cooldown) {
		this.missTime = cooldown;
	}

	@Override
	public boolean ferrite$triggerAttack() {
		this.missTime = 0;
		return this.startAttack();
	}

	@Inject(method = "runTick(Z)V", at = @At("HEAD"), require = 0)
	private void onRunTick(boolean renderLevel, CallbackInfo ci) {
		ModelSidesCache.INSTANCE.onRenderFrame((Minecraft) (Object) this);
	}

	@Inject(method = "startAttack()Z", at = @At("HEAD"), require = 0)
	private void onPreStartAttack(CallbackInfoReturnable<Boolean> cir) {
		if (ModelSidesCache.INSTANCE.isEnabled()) {
			this.missTime = 0;
		}
	}

	@Inject(
		method = "shouldEntityAppearGlowing(Lnet/minecraft/world/entity/Entity;)Z",
		at = @At("HEAD"),
		cancellable = true
	)
	private void onShouldEntityAppearGlowing(Entity entity, CallbackInfoReturnable<Boolean> cir) {
		if (BakedQuadDeduplicator.INSTANCE.shouldHighlightEntity(entity)) {
			cir.setReturnValue(true);
		}
	}

	@Inject(method = "allowsTelemetry()Z", at = @At("HEAD"), cancellable = true)
	private void onAllowsTelemetry(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}

	@Inject(method = "extraTelemetryAvailable()Z", at = @At("HEAD"), cancellable = true)
	private void onExtraTelemetryAvailable(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}
}
