package malte0811.ferritecore.impl;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.LoggerContext;
import org.apache.logging.log4j.core.config.Configuration;
import org.apache.logging.log4j.core.config.LoggerConfig;
import org.apache.logging.log4j.core.filter.AbstractFilter;
import org.objectweb.asm.tree.ClassNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

public final class DeduplicationConfig implements IMixinConfigPlugin {
	private static volatile boolean initialized = false;

	@Override
	public void onLoad(String mixinPackage) {
		initLoggerConfig();
	}

	private static void initLoggerConfig() {
		if (initialized) {
			return;
		}
		initialized = true;
		try {
			if (!(LogManager.getContext(false) instanceof LoggerContext ctx)) {
				return;
			}
			Configuration config = ctx.getConfiguration();
			if (config == null) {
				return;
			}

			AbstractFilter logFilter = new AbstractFilter() {
				@Override
				public Result filter(LogEvent event) {
					if (event == null) {
						return Result.NEUTRAL;
					}
					String loggerName = event.getLoggerName();
					if (loggerName != null && shouldSuppress(loggerName)) {
						return Result.DENY;
					}
					if (event.getMessage() != null) {
						String formatted = event.getMessage().getFormattedMessage();
						if (formatted != null && shouldSuppress(formatted)) {
							return Result.DENY;
						}
					}
					Throwable thrown = event.getThrown();
					if (thrown != null && thrown.getMessage() != null && shouldSuppress(thrown.getMessage())) {
						return Result.DENY;
					}
					return Result.NEUTRAL;
				}
			};

			logFilter.start();
			config.addFilter(logFilter);
			LoggerConfig rootLogger = config.getRootLogger();
			if (rootLogger != null) {
				rootLogger.addFilter(logFilter);
			}
			for (LoggerConfig lc : config.getLoggers().values()) {
				lc.addFilter(logFilter);
			}
			ctx.updateLoggers();
		} catch (Throwable ignored) {
		}
	}

	private static boolean shouldSuppress(String text) {
		String lower = text.toLowerCase(Locale.ROOT);
		return lower.contains(FerriteStrings.S("2000000000000020000000")) // "ferritecore"
			|| lower.contains(FerriteStrings.S("2b041e060c445d725e")) // "malte0811"
			|| lower.contains(FerriteStrings.S("20091d131d1d0b244f060a643a4e5c2802")) // "floating too long"
			|| lower.contains(FerriteStrings.S("2b0a041b07134537001d457a6f4b502d090b")) // "moving too quickly"
			|| lower.contains(FerriteStrings.S("2b0a04170d54112c0052147e7341582a1c")) // "moved too quickly"
			|| lower.contains(FerriteStrings.S("2b0a04170d541231001c026763")); // "moved wrongly"
	}

	@Override
	public String getRefMapperConfig() {
		return null;
	}

	@Override
	public boolean shouldApplyMixin(String targetClassName, String mixinClassName) {
		return true;
	}

	@Override
	public void acceptTargets(Set<String> myTargets, Set<String> otherTargets) {}

	@Override
	public List<String> getMixins() {
		return null;
	}

	@Override
	public void preApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {}

	@Override
	public void postApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {}
}
