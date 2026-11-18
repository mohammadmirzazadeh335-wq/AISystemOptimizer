<?php
/**
 * Reusable section/component library.
 *
 * Every template is a builder-agnostic spec (rows → elements) that the
 * Gutenberg and Elementor adapters materialize into real markup. The model
 * overrides texts/images/links per section; the design system supplies the
 * styling tokens. Specs are plain data — no eval, no remote code.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Section_Library
 */
class Section_Library {

	/**
	 * All available section types with default specs.
	 *
	 * @return array[] type => spec factory inputs.
	 */
	public static function types() {
		return array(
			'header'        => __( 'Site header with logo and navigation', 'ai-wordpress-copilot' ),
			'footer'        => __( 'Site footer with links and copyright', 'ai-wordpress-copilot' ),
			'hero'          => __( 'Hero banner with headline, text and CTA', 'ai-wordpress-copilot' ),
			'nav'           => __( 'Navigation links bar', 'ai-wordpress-copilot' ),
			'mega_menu'     => __( 'Mega menu with grouped link columns', 'ai-wordpress-copilot' ),
			'sidebar'       => __( 'Sidebar with widgets/links', 'ai-wordpress-copilot' ),
			'features'      => __( 'Feature cards grid', 'ai-wordpress-copilot' ),
			'stats'         => __( 'Statistics counters row', 'ai-wordpress-copilot' ),
			'testimonials'  => __( 'Customer testimonials', 'ai-wordpress-copilot' ),
			'pricing'       => __( 'Pricing plans table', 'ai-wordpress-copilot' ),
			'faq'           => __( 'FAQ list', 'ai-wordpress-copilot' ),
			'gallery'       => __( 'Image gallery grid', 'ai-wordpress-copilot' ),
			'blog_grid'     => __( 'Blog posts grid (latest posts)', 'ai-wordpress-copilot' ),
			'cta'           => __( 'Call-to-action banner', 'ai-wordpress-copilot' ),
			'contact'       => __( 'Contact section with details', 'ai-wordpress-copilot' ),
			'newsletter'    => __( 'Newsletter signup section', 'ai-wordpress-copilot' ),
			'product_grid'  => __( 'WooCommerce product grid', 'ai-wordpress-copilot' ),
			'product_card'  => __( 'Single product highlight card', 'ai-wordpress-copilot' ),
			'category_grid' => __( 'Product category grid', 'ai-wordpress-copilot' ),
			'landing_hero'  => __( 'Landing hero with image background', 'ai-wordpress-copilot' ),
			'html'          => __( 'Custom HTML block', 'ai-wordpress-copilot' ),
		);
	}

	/**
	 * Build a section spec with content overrides.
	 *
	 * @param string $type      Section type.
	 * @param array  $content   Overrides: texts, images, links, items.
	 * @param array  $design    Design system tokens.
	 * @return array|null Spec with type/label/layout/elements.
	 */
	public static function section( $type, array $content = array(), array $design = array() ) {
		if ( ! array_key_exists( $type, self::types() ) ) {
			return null;
		}
		$method = 'spec_' . str_replace( '-', '_', $type );
		if ( ! method_exists( __CLASS__, $method ) ) {
			return null;
		}
		$spec = self::$method( $content, $design );
		$spec['type'] = $type;
		return $spec;
	}

	/**
	 * Get (string|array) with fallback.
	 *
	 * @param array  $content Content.
	 * @param string $key     Key.
	 * @param string $default Default.
	 * @return string
	 */
	private static function t( array $content, $key, $default ) {
		$v = isset( $content[ $key ] ) ? $content[ $key ] : $default;
		return is_scalar( $v ) ? (string) $v : $default;
	}

	/**
	 * Get list with fallback.
	 *
	 * @param array  $content Content.
	 * @param string $key     Key.
	 * @param array  $default Default.
	 * @return array
	 */
	private static function l( array $content, $key, array $default ) {
		$v = isset( $content[ $key ] ) ? $content[ $key ] : $default;
		return is_array( $v ) ? $v : $default;
	}

	/*
	|--------------------------------------------------------------------------
	| Spec factories. Each returns: label, layout, style, elements.
	|--------------------------------------------------------------------------
	*/

	/**
	 * Hero.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_hero( array $content, array $design ) {
		return array(
			'label'    => __( 'Hero', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'center' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'lg' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 1, 'text' => self::t( $content, 'heading', __( 'وب‌سایت شما، هوشمندانه ساخته شده', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'text', __( 'تجربه‌ای مدرن، سریع و زیبا برای مخاطبان شما. همه چیز با هوش مصنوعی مدیریت می‌شود.', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'button', 'text' => self::t( $content, 'button_text', __( 'شروع کنید', 'ai-wordpress-copilot' ) ), 'url' => self::t( $content, 'button_url', '#contact' ) ),
			),
		);
	}

	/**
	 * Landing hero with background image.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_landing_hero( array $content, array $design ) {
		return array(
			'label'    => __( 'Landing hero', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'center' ),
			'style'    => array( 'bg' => 'primary', 'padding' => 'lg', 'image_bg' => self::t( $content, 'image', '' ) ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 1, 'text' => self::t( $content, 'heading', __( 'محصول ما را کشف کنید', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'text', __( 'راه‌حلی کامل برای نیازهای شما، با پشتیبانی حرفه‌ای.', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'button', 'text' => self::t( $content, 'button_text', __( 'مشاهده محصولات', 'ai-wordpress-copilot' ) ), 'url' => self::t( $content, 'button_url', '#products' ) ),
			),
		);
	}

	/**
	 * Features grid (3 cards).
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_features( array $content, array $design ) {
		$items = self::l(
			$content,
			'items',
			array(
				array( 'title' => __( 'سرعت بالا', 'ai-wordpress-copilot' ), 'text' => __( 'بهینه‌سازی کامل برای بارگذاری سریع.', 'ai-wordpress-copilot' ) ),
				array( 'title' => __( 'طراحی مدرن', 'ai-wordpress-copilot' ), 'text' => __( 'ظاهری حرفه‌ای در همه دستگاه‌ها.', 'ai-wordpress-copilot' ) ),
				array( 'title' => __( 'پشتیبانی قوی', 'ai-wordpress-copilot' ), 'text' => __( 'همراه شما در هر مرحله.', 'ai-wordpress-copilot' ) ),
			)
		);
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'ویژگی‌های ما', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $items, 0, 6 ) as $item ) {
			$elements[] = array(
				'kind'     => 'card',
				'title'    => self::t( (array) $item, 'title', '' ),
				'text'     => self::t( (array) $item, 'text', '' ),
			);
		}
		return array(
			'label'    => __( 'Features', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => min( 3, max( 1, count( $elements ) - 1 ) ), 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * Stats row.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_stats( array $content, array $design ) {
		$items = self::l(
			$content,
			'items',
			array(
				array( 'value' => '+۱۲۰۰', 'label' => __( 'مشتری راضی', 'ai-wordpress-copilot' ) ),
				array( 'value' => '۹۸٪', 'label' => __( 'رضایت', 'ai-wordpress-copilot' ) ),
				array( 'value' => '+۵۰', 'label' => __( 'پروژه موفق', 'ai-wordpress-copilot' ) ),
				array( 'value' => '۲۴/۷', 'label' => __( 'پشتیبانی', 'ai-wordpress-copilot' ) ),
			)
		);
		$elements = array();
		foreach ( array_slice( $items, 0, 6 ) as $item ) {
			$elements[] = array(
				'kind'  => 'stat',
				'value' => self::t( (array) $item, 'value', '' ),
				'label' => self::t( (array) $item, 'label', '' ),
			);
		}
		return array(
			'label'    => __( 'Stats', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => count( $elements ), 'align' => 'center' ),
			'style'    => array( 'bg' => 'primary', 'padding' => 'md' ),
			'elements' => $elements,
		);
	}

	/**
	 * Testimonials.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_testimonials( array $content, array $design ) {
		$items = self::l(
			$content,
			'items',
			array(
				array( 'quote' => __( 'کیفیت کار عالی بود و همه چیز به موقع تحویل داده شد.', 'ai-wordpress-copilot' ), 'author' => __( 'مشتری ۱', 'ai-wordpress-copilot' ) ),
				array( 'quote' => __( 'تجربه همکاری بسیار خوبی داشتیم.', 'ai-wordpress-copilot' ), 'author' => __( 'مشتری ۲', 'ai-wordpress-copilot' ) ),
			)
		);
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'نظر مشتریان', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $items, 0, 4 ) as $item ) {
			$elements[] = array(
				'kind'   => 'quote',
				'text'   => self::t( (array) $item, 'quote', '' ),
				'author' => self::t( (array) $item, 'author', '' ),
			);
		}
		return array(
			'label'    => __( 'Testimonials', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => min( 2, max( 1, count( $elements ) - 1 ) ), 'align' => 'left' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * Pricing.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_pricing( array $content, array $design ) {
		$items = self::l(
			$content,
			'items',
			array(
				array( 'title' => __( 'پایه', 'ai-wordpress-copilot' ), 'price' => '۹۹٬۰۰۰', 'features' => array( __( 'ویژگی ۱', 'ai-wordpress-copilot' ), __( 'ویژگی ۲', 'ai-wordpress-copilot' ) ), 'button' => __( 'انتخاب', 'ai-wordpress-copilot' ) ),
				array( 'title' => __( 'حرفه‌ای', 'ai-wordpress-copilot' ), 'price' => '۱۹۹٬۰۰۰', 'features' => array( __( 'همه ویژگی‌های پایه', 'ai-wordpress-copilot' ), __( 'پشتیبانی ویژه', 'ai-wordpress-copilot' ) ), 'button' => __( 'انتخاب', 'ai-wordpress-copilot' ), 'featured' => true ),
			)
		);
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'قیمت‌ها', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $items, 0, 4 ) as $item ) {
			$features = isset( $item['features'] ) && is_array( $item['features'] ) ? $item['features'] : array();
			$elements[] = array(
				'kind'     => 'price_card',
				'title'    => self::t( (array) $item, 'title', '' ),
				'price'    => self::t( (array) $item, 'price', '' ),
				'features' => array_map( 'strval', array_slice( $features, 0, 8 ) ),
				'button'   => self::t( (array) $item, 'button', __( 'خرید', 'ai-wordpress-copilot' ) ),
				'featured' => ! empty( $item['featured'] ),
			);
		}
		return array(
			'label'    => __( 'Pricing', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => min( 3, max( 1, count( $elements ) - 1 ) ), 'align' => 'center' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * FAQ.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_faq( array $content, array $design ) {
		$items = self::l(
			$content,
			'items',
			array(
				array( 'q' => __( 'چگونه شروع کنم؟', 'ai-wordpress-copilot' ), 'a' => __( 'از دکمه تماس با ما استفاده کنید.', 'ai-wordpress-copilot' ) ),
				array( 'q' => __( 'آیا پشتیبانی دارید؟', 'ai-wordpress-copilot' ), 'a' => __( 'بله، پشتیبانی ۲۴ ساعته فعال است.', 'ai-wordpress-copilot' ) ),
			)
		);
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'پرسش‌های متداول', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $items, 0, 10 ) as $item ) {
			$elements[] = array(
				'kind' => 'qa',
				'q'    => self::t( (array) $item, 'q', '' ),
				'a'    => self::t( (array) $item, 'a', '' ),
			);
		}
		return array(
			'label'    => __( 'FAQ', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * CTA banner.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_cta( array $content, array $design ) {
		return array(
			'label'    => __( 'CTA', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'center' ),
			'style'    => array( 'bg' => 'secondary', 'padding' => 'lg' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'آماده‌اید شروع کنید؟', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'text', __( 'همین امروز سفارش دهید.', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'button', 'text' => self::t( $content, 'button_text', __( 'تماس با ما', 'ai-wordpress-copilot' ) ), 'url' => self::t( $content, 'button_url', '#contact' ) ),
			),
		);
	}

	/**
	 * Contact.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_contact( array $content, array $design ) {
		return array(
			'id'       => 'contact',
			'label'    => __( 'Contact', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'lg' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'تماس با ما', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'address', __( 'تهران، خیابان آزادی، پلاک ۱', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'phone', __( 'تلفن: ۰۲۱-۱۲۳۴۵۶۷۸', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'email', __( 'ایمیل: info@example.com', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'html', 'html' => self::t( $content, 'form_html', '<form class="aiwc-contact-form"><input type="text" name="name" placeholder="' . __( 'نام', 'ai-wordpress-copilot' ) . '" /><input type="email" name="email" placeholder="' . __( 'ایمیل', 'ai-wordpress-copilot' ) . '" /><textarea name="message" placeholder="' . __( 'پیام', 'ai-wordpress-copilot' ) . '"></textarea><button type="submit">' . __( 'ارسال', 'ai-wordpress-copilot' ) . '</button></form>' ) ),
			),
		);
	}

	/**
	 * Newsletter.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_newsletter( array $content, array $design ) {
		return array(
			'label'    => __( 'Newsletter', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'center' ),
			'style'    => array( 'bg' => 'primary', 'padding' => 'md' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'خبرنامه ما', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'text', __( 'آخرین اخبار را در ایمیل خود دریافت کنید.', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'html', 'html' => '<form class="aiwc-newsletter"><input type="email" name="email" placeholder="' . __( 'ایمیل شما', 'ai-wordpress-copilot' ) . '" /><button type="submit">' . __( 'عضویت', 'ai-wordpress-copilot' ) . '</button></form>' ),
			),
		);
	}

	/**
	 * Gallery.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_gallery( array $content, array $design ) {
		$images = self::l( $content, 'images', array() );
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'گالری تصاویر', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $images, 0, 9 ) as $img ) {
			$elements[] = array( 'kind' => 'image', 'url' => self::t( (array) $img, 'url', is_scalar( $img ) ? (string) $img : '' ), 'alt' => self::t( (array) $img, 'alt', '' ) );
		}
		return array(
			'label'    => __( 'Gallery', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 3, 'align' => 'center' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * Blog grid (latest posts).
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_blog_grid( array $content, array $design ) {
		return array(
			'label'    => __( 'Blog grid', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 3, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'آخرین مقالات', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'latest_posts', 'count' => min( 9, max( 1, (int) self::t( $content, 'count', '3' ) ) ) ),
			),
		);
	}

	/**
	 * Product grid (WooCommerce).
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_product_grid( array $content, array $design ) {
		return array(
			'id'       => 'products',
			'label'    => __( 'Product grid', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 3, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'lg' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'محصولات ما', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'products', 'count' => min( 12, max( 1, (int) self::t( $content, 'count', '6' ) ) ), 'columns' => 3 ),
			),
		);
	}

	/**
	 * Product card.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_product_card( array $content, array $design ) {
		return array(
			'label'    => __( 'Product card', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'center' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'md' ),
			'elements' => array(
				array( 'kind' => 'image', 'url' => self::t( $content, 'image', '' ), 'alt' => self::t( $content, 'title', '' ) ),
				array( 'kind' => 'heading', 'level' => 3, 'text' => self::t( $content, 'title', __( 'نام محصول', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'text', 'text' => self::t( $content, 'price', '' ) ),
				array( 'kind' => 'button', 'text' => self::t( $content, 'button_text', __( 'افزودن به سبد', 'ai-wordpress-copilot' ) ), 'url' => self::t( $content, 'button_url', '#' ) ),
			),
		);
	}

	/**
	 * Category grid.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_category_grid( array $content, array $design ) {
		$items = self::l( $content, 'items', array() );
		$elements = array( array( 'kind' => 'heading', 'level' => 2, 'text' => self::t( $content, 'heading', __( 'دسته‌بندی‌ها', 'ai-wordpress-copilot' ) ) ) );
		foreach ( array_slice( $items, 0, 8 ) as $item ) {
			$elements[] = array(
				'kind'  => 'category_card',
				'title' => self::t( (array) $item, 'title', '' ),
				'url'   => self::t( (array) $item, 'url', '#' ),
			);
		}
		if ( count( $elements ) === 1 && function_exists( 'wc_get_product_category_list' ) ) {
			$elements[] = array( 'kind' => 'product_categories', 'count' => 6 );
		}
		return array(
			'label'    => __( 'Category grid', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 3, 'align' => 'center' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * Header.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_header( array $content, array $design ) {
		$links = self::l( $content, 'links', array() );
		$elements = array(
			array( 'kind' => 'heading', 'level' => 3, 'text' => self::t( $content, 'logo', get_bloginfo( 'name' ) ) ),
		);
		if ( $links ) {
			$elements[] = array( 'kind' => 'nav_links', 'links' => $links );
		} else {
			$elements[] = array( 'kind' => 'navigation', 'menu' => self::t( $content, 'menu', '' ) );
		}
		return array(
			'label'    => __( 'Header', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'sm' ),
			'elements' => $elements,
		);
	}

	/**
	 * Footer.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_footer( array $content, array $design ) {
		$columns = self::l( $content, 'columns', array() );
		$elements = array();
		if ( $columns ) {
			foreach ( array_slice( $columns, 0, 4 ) as $col ) {
				$elements[] = array(
					'kind'   => 'link_group',
					'title'  => self::t( (array) $col, 'title', '' ),
					'links'  => self::l( (array) $col, 'links', array() ),
				);
			}
		} else {
			$elements[] = array( 'kind' => 'text', 'text' => self::t( $content, 'about', get_bloginfo( 'description' ) ) );
		}
		$elements[] = array( 'kind' => 'text', 'text' => self::t( $content, 'copyright', '© ' . gmdate( 'Y' ) . ' ' . get_bloginfo( 'name' ) ) );
		return array(
			'label'    => __( 'Footer', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => max( 1, min( 4, count( $elements ) - 1 ) ), 'align' => 'left' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'lg' ),
			'elements' => $elements,
		);
	}

	/**
	 * Nav links bar.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_nav( array $content, array $design ) {
		return array(
			'label'    => __( 'Navigation', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'sm' ),
			'elements' => array(
				array( 'kind' => 'navigation', 'menu' => self::t( $content, 'menu', '' ) ),
			),
		);
	}

	/**
	 * Mega menu (grouped link columns).
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_mega_menu( array $content, array $design ) {
		$groups = self::l(
			$content,
			'groups',
			array(
				array( 'title' => __( 'محصولات', 'ai-wordpress-copilot' ), 'links' => array( array( 'text' => __( 'همه محصولات', 'ai-wordpress-copilot' ), 'url' => '#' ), array( 'text' => __( 'جدیدترین‌ها', 'ai-wordpress-copilot' ), 'url' => '#' ) ) ),
				array( 'title' => __( 'خدمات', 'ai-wordpress-copilot' ), 'links' => array( array( 'text' => __( 'مشاوره', 'ai-wordpress-copilot' ), 'url' => '#' ) ) ),
			)
		);
		$elements = array();
		foreach ( array_slice( $groups, 0, 6 ) as $g ) {
			$elements[] = array(
				'kind'  => 'link_group',
				'title' => self::t( (array) $g, 'title', '' ),
				'links' => self::l( (array) $g, 'links', array() ),
			);
		}
		return array(
			'label'    => __( 'Mega menu', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => min( 4, max( 1, count( $elements ) ) ), 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'md' ),
			'elements' => $elements,
		);
	}

	/**
	 * Sidebar.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_sidebar( array $content, array $design ) {
		return array(
			'label'    => __( 'Sidebar', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'surface', 'padding' => 'md' ),
			'elements' => array(
				array( 'kind' => 'heading', 'level' => 3, 'text' => self::t( $content, 'heading', __( 'کناره', 'ai-wordpress-copilot' ) ) ),
				array( 'kind' => 'navigation', 'menu' => self::t( $content, 'menu', '' ) ),
				array( 'kind' => 'html', 'html' => self::t( $content, 'html', '' ) ),
			),
		);
	}

	/**
	 * Custom HTML.
	 *
	 * @param array $content Content.
	 * @param array $design  Design.
	 * @return array
	 */
	private static function spec_html( array $content, array $design ) {
		return array(
			'label'    => __( 'Custom HTML', 'ai-wordpress-copilot' ),
			'layout'   => array( 'columns' => 1, 'align' => 'left' ),
			'style'    => array( 'bg' => 'bg', 'padding' => 'md' ),
			'elements' => array(
				array( 'kind' => 'html', 'html' => self::t( $content, 'html', '<div></div>' ) ),
			),
		);
	}

	/*
	|--------------------------------------------------------------------------
	| Reusable components (stored snippets of specs).
	|--------------------------------------------------------------------------
	*/

	/**
	 * Save a reusable component.
	 *
	 * @param string $name Name.
	 * @param array  $spec Section spec.
	 * @return bool
	 */
	public static function save_component( $name, array $spec ) {
		$name = sanitize_key( str_replace( ' ', '_', (string) $name ) );
		if ( '' === $name ) {
			return false;
		}
		$components = get_option( 'aiwc_components', array() );
		if ( ! is_array( $components ) ) {
			$components = array();
		}
		$components[ $name ] = array(
			'name'      => $name,
			'spec'      => $spec,
			'updated_at' => current_time( 'mysql' ),
		);
		update_option( 'aiwc_components', $components, false );
		return true;
	}

	/**
	 * List reusable components.
	 *
	 * @return array
	 */
	public static function list_components() {
		$components = get_option( 'aiwc_components', array() );
		return is_array( $components ) ? $components : array();
	}

	/**
	 * Get one component spec.
	 *
	 * @param string $name Name.
	 * @return array|null
	 */
	public static function get_component( $name ) {
		$components = self::list_components();
		$name       = sanitize_key( (string) $name );
		return isset( $components[ $name ] ) ? $components[ $name ]['spec'] : null;
	}

	/**
	 * Delete a component.
	 *
	 * @param string $name Name.
	 * @return bool
	 */
	public static function delete_component( $name ) {
		$components = self::list_components();
		$name       = sanitize_key( (string) $name );
		if ( ! isset( $components[ $name ] ) ) {
			return false;
		}
		unset( $components[ $name ] );
		update_option( 'aiwc_components', $components, false );
		return true;
	}
}
