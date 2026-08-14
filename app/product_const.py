CATEGORY_LABELS = {
    "CASE": "📱 Case", "CHARGER": "🔌 Charger", "CABLE": "🔗 Cable",
    "SCREEN": "🖥️ Screen", "BATTERY": "🔋 Battery", "ACCESSORY": "🎧 Accessory", "PART": "🔧 Part",
    "LAPTOP": "💻 Laptop/Chromebook", "LAPTOP_ACC": "💼 Laptop Accessory", "GAMING": "🎮 Gaming Accessory",
}
CAT_SUBCATEGORIES = {
    "CASE": ["OtterBox", "Speck", "UAG", "Moment", "Case-Mate", "RhinoShield", "Peel", "Casetify", "Mous", "Nomad", "Apple", "Generic"],
    "CHARGER": ["Anker", "Apple", "Belkin", "Samsung", "RAVPower", "Generic"],
    "CABLE": ["Anker", "Apple", "Belkin", "Generic"],
    "SCREEN": ["OEM", "Aftermarket", "Glass-Only"],
    "BATTERY": ["OEM Grade", "Aftermarket"],
    "ACCESSORY": ["Screen Protector", "Wireless Charging", "PopSocket", "Holder", "Other"],
    "PART": ["General"],
    "LAPTOP": ["Apple", "Dell", "HP", "Lenovo", "ASUS", "Acer", "Microsoft", "Samsung", "Google", "Generic"],
    "LAPTOP_ACC": ["Logitech", "Anker", "Belkin", "Targus", "Apple", "STM", "Incase", "Generic"],
    "GAMING": ["Logitech", "Razer", "SteelSeries", "HyperX", "Corsair", "Sony", "Microsoft", "Nintendo", "8BitDo", "Generic"],
}
ALL_BRANDS = sorted(set(b for subs in CAT_SUBCATEGORIES.values() for b in subs))
