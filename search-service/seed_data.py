"""
Seed script to populate database with sample vehicles and batteries
Includes top 10 vehicle brands and top 10 battery brands
"""
from app import create_app
from models import db, Vehicle, Battery
import random

# Top 10 Vehicle Brands with models
VEHICLE_BRANDS = {
    "VinFast": ["VF e34", "VF 5", "VF 8", "VF 9", "VF 3"],
    "Tesla": ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck"],
    "BYD": ["Atto 3", "Seal", "Dolphin", "Han", "Tang"],
    "BMW": ["iX3", "i4", "iX", "i7", "i5"],
    "Mercedes-Benz": ["EQC", "EQS", "EQE", "EQA", "EQB"],
    "Audi": ["e-tron", "e-tron GT", "Q4 e-tron", "Q8 e-tron", "A6 e-tron"],
    "Nissan": ["Leaf", "Ariya", "Sakura"],
    "Hyundai": ["Ioniq 5", "Ioniq 6", "Kona Electric", "Ioniq Electric"],
    "Kia": ["EV6", "EV9", "Niro EV", "Soul EV"],
    "Chevrolet": ["Bolt EV", "Bolt EUV", "Blazer EV", "Equinox EV"]
}

# Top 10 Battery Brands with specs
BATTERY_BRANDS = [
    "CATL",
    "LG Energy Solution", 
    "Panasonic",
    "Samsung SDI",
    "BYD Battery",
    "SK Innovation",
    "Tesla Battery",
    "Envision AESC",
    "SVOLT",
    "Gotion High-Tech"
]

# Vietnam provinces for realistic locations
VN_PROVINCES = [
    "Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ",
    "Bình Dương", "Đồng Nai", "Khánh Hòa", "Nghệ An", "Bắc Ninh"
]

def seed_vehicles():
    """Create sample vehicles for all brands"""
    print("🚗 Seeding vehicles...")
    vehicles = []
    
    for brand, models in VEHICLE_BRANDS.items():
        for model in models:
            # Create 2-3 listings per model
            for i in range(random.randint(2, 3)):
                year = random.randint(2020, 2024)
                km = random.randint(500, 50000)
                base_price = random.randint(300_000_000, 2_000_000_000)
                battery_kwh = random.choice([35, 50, 60, 75, 100])
                condition = random.choice(["new", "used", "good", "fair"])
                seller_id = random.randint(1, 10)
                
                vehicle = Vehicle(
                    brand=brand,
                    model=model,
                    year=year,
                    km=km,
                    price=base_price,
                    condition=condition,
                    battery_capacity_kwh=battery_kwh,
                    seller_id=seller_id
                )
                vehicles.append(vehicle)
    
    db.session.bulk_save_objects(vehicles)
    print(f"✅ Created {len(vehicles)} vehicles")

def seed_batteries():
    """Create sample batteries for all brands"""
    print("🔋 Seeding batteries...")
    batteries = []
    
    for brand in BATTERY_BRANDS:
        # Create 3-5 listings per brand
        for i in range(random.randint(3, 5)):
            capacity = random.choice([40, 50, 60, 75, 100, 120])
            cycles = random.randint(50, 1500)
            health = random.randint(75, 100)
            year = random.randint(2019, 2024)
            base_price = int(capacity * 10_000_000)  # 10M per kWh
            condition = random.choice(["new", "used", "good", "fair"])
            seller_id = random.randint(1, 10)
            
            battery = Battery(
                brand=brand,
                capacity_kwh=capacity,
                cycles=cycles,
                health_percent=health,
                price=base_price + random.randint(-5_000_000, 10_000_000),
                year=year,
                condition=condition,
                seller_id=seller_id
            )
            batteries.append(battery)
    
    db.session.bulk_save_objects(batteries)
    print(f"✅ Created {len(batteries)} batteries")

def main():
    app = create_app()
    with app.app_context():
        print("🗄️  Creating database tables...")
        db.create_all()
        
        # Check if already seeded
        if Vehicle.query.count() > 0 or Battery.query.count() > 0:
            print("⚠️  Database already has data. Skipping seed.")
            print(f"   Vehicles: {Vehicle.query.count()}")
            print(f"   Batteries: {Battery.query.count()}")
            return
        
        seed_vehicles()
        seed_batteries()
        
        db.session.commit()
        print("\n🎉 Database seeded successfully!")
        print(f"   Total Vehicles: {Vehicle.query.count()}")
        print(f"   Total Batteries: {Battery.query.count()}")

if __name__ == "__main__":
    main()
