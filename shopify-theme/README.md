# Hroofy | حروفي: Shopify Theme Customizations

Custom Shopify OS 2.0 files for the Hroofy kids' coloring-book POD store,
layered on top of the **Horizon** theme. The files mirror the theme folder
structure, so they can be copied as-is or pushed with `shopify theme push`.

| Path | What it is |
|------|------------|
| `sections/kids-playful-hero.liquid` | Animated Toy-UI hero with trust-badge blocks |
| `sections/age-skill-navigator.liquid` | Tabbed age / skill collection cards |
| `sections/interactive-coloring-preview.liquid` | "Try coloring before you buy" SVG widget (product template) |
| `snippets/cart-free-shipping-goal.liquid` | Free-shipping + free-gift progress bar for the cart drawer |
| `snippets/hroofy-brand-styles.liquid` | Brand fonts (Baloo Bhaijaan 2 + Cairo) and color tokens |
| `snippets/cart-drawer.liquid` | Horizon cart drawer + one line rendering the goal bar |
| `layout/theme.liquid` | Horizon layout + one line rendering the brand styles |
| `templates/index.json`, `templates/product.json` | Home and product templates wired to the new sections |
| `config/settings_data.json` | Brand color palette, button and card radii |
| `docs/HROOFY_STORE_GUIDE.md` | Brand identity, catalog, pricing and AI image prompts |

```bash
shopify theme push --theme "Hroofy Kids - Draft" --path shopify-theme --nodelete
```
