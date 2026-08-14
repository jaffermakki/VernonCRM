"""
Reference data for the case-inventory bulk generator (Products page).
Not exhaustive by design — new phones ship every year, and a shop like
this needs to add a model that isn't listed here without waiting on a
code update. Every dropdown built from this backs onto a free-text
field, so "Other" plus manual typing always works.
"""

PHONE_MODELS = {
    "Apple": [
        "iPhone 12", "iPhone 12 Mini", "iPhone 12 Pro", "iPhone 12 Pro Max",
        "iPhone 13", "iPhone 13 Mini", "iPhone 13 Pro", "iPhone 13 Pro Max",
        "iPhone 14", "iPhone 14 Plus", "iPhone 14 Pro", "iPhone 14 Pro Max",
        "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
        "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max",
        "iPhone 17", "iPhone 17 Pro", "iPhone 17 Pro Max", "iPhone 17 Air",
        "iPhone SE (3rd gen)",
    ],
    "Samsung": [
        "Galaxy S22", "Galaxy S22+", "Galaxy S22 Ultra",
        "Galaxy S23", "Galaxy S23+", "Galaxy S23 Ultra", "Galaxy S23 FE",
        "Galaxy S24", "Galaxy S24+", "Galaxy S24 Ultra", "Galaxy S24 FE",
        "Galaxy S25", "Galaxy S25+", "Galaxy S25 Ultra",
        "Galaxy Z Flip 5", "Galaxy Z Flip 6", "Galaxy Z Fold 5", "Galaxy Z Fold 6",
        "Galaxy A14", "Galaxy A15", "Galaxy A25", "Galaxy A35", "Galaxy A55",
    ],
    "Google": [
        "Pixel 6", "Pixel 6 Pro", "Pixel 6a",
        "Pixel 7", "Pixel 7 Pro", "Pixel 7a",
        "Pixel 8", "Pixel 8 Pro", "Pixel 8a",
        "Pixel 9", "Pixel 9 Pro", "Pixel 9 Pro XL", "Pixel 9a",
    ],
    "Motorola": [
        "Moto G Power", "Moto G Stylus", "Moto G Play", "Moto G 5G",
        "Moto Edge", "Moto Edge+", "Moto Razr", "Moto Razr+",
    ],
    "Other": [],  # free-text model — for any brand/model not listed above
}

PHONE_BRANDS = list(PHONE_MODELS.keys())

CASE_COLORS = [
    "Black", "Clear", "White", "Navy", "Red", "Blue", "Green", "Pink",
    "Purple", "Gray", "Gold", "Rose Gold", "Teal", "Yellow", "Orange",
]

# Suggested variant_group names — matches the seven case styles this
# shop actually carries. Purely a convenience list for the generator's
# dropdown; variant_group itself stays free text so a new style can be
# typed in without a code change.
COMMON_CASE_STYLES = [
    "Hard Ring Case", "Soft Ring Case", "Wallet Style Case",
    "Apple Silicone Case", "Dotted Armor Case", "Clear Case",
    "Back Wallet Case", "Limited Edition Case",
]

LAPTOP_MODELS = {
    "Apple": [
        "MacBook Air 13\" (M2/M3)", "MacBook Air 15\"", "MacBook Pro 14\"", "MacBook Pro 16\"",
    ],
    "Dell": [
        "XPS 13", "XPS 15", "Inspiron 15", "Latitude 14",
    ],
    "HP": [
        "Pavilion 15", "Spectre x360", "EliteBook", "Chromebook 14",
    ],
    "Lenovo": [
        "ThinkPad X1 Carbon", "IdeaPad 3", "Yoga 7i", "IdeaPad Flex 5 Chromebook",
    ],
    "ASUS": [
        "ZenBook 14", "VivoBook 15", "ROG Zephyrus", "Chromebook Flip",
    ],
    "Acer": [
        "Aspire 5", "Swift 3", "Chromebook Spin 314", "Chromebook 315",
    ],
    "Microsoft": [
        "Surface Laptop 5", "Surface Laptop Go 3", "Surface Pro 9",
    ],
    "Samsung": [
        "Galaxy Book4", "Galaxy Book4 Pro", "Galaxy Chromebook Go",
    ],
    "Google": [
        "Pixelbook Go",
    ],
    "Other": [],  # free-text model
}

# Console/controller variant products — skins, silicone grips, carrying
# cases that come in the same "one style x several models x several
# colors" shape as phone cases and laptop sleeves. A specific gaming
# accessory that ISN'T model-specific (a particular Razer headset, a
# particular mechanical keyboard) is a single SKU and belongs in the
# regular Add Product form instead — this list is only for the subset
# of gaming inventory that genuinely varies by console/controller model.
CONSOLE_MODELS = {
    "Sony": ["PS5", "PS5 Slim", "PS5 Pro", "DualSense Controller", "PS4"],
    "Microsoft": ["Xbox Series X", "Xbox Series S", "Xbox Controller", "Xbox One"],
    "Nintendo": ["Switch", "Switch OLED", "Switch Lite", "Joy-Con"],
    "Valve": ["Steam Deck", "Steam Deck OLED"],
    "Other": [],  # free-text model
}

# Suggested variant_group names for the laptop/gaming side of the
# generator, same free-text-friendly role as COMMON_CASE_STYLES above.
COMMON_LAPTOP_GAMING_STYLES = [
    "Laptop Sleeve", "Laptop Hard Shell Case", "Laptop Skin/Decal",
    "Controller Skin", "Controller Silicone Case", "Console Carrying Case",
]

