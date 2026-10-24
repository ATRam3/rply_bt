"""
Test Gemini API speed to diagnose the slowness
"""
import google.genai as genai
import os
import time
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

load_dotenv()
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Create test images of different sizes
def create_test_image(size):
    img = Image.new('RGB', size, color='white')
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    buf.seek(0)
    return Image.open(buf)

print("="*80)
print("GEMINI API SPEED TEST")
print("="*80)

# Test different models and image sizes
tests = [
    ("gemini-3.5-flash-lite", 384, "Small image"),
    ("gemini-3.5-flash-lite", 768, "Medium image"),
    ("gemini-3.5-flash", 384, "Small image"),
    ("gemini-3.5-flash", 768, "Medium image"),
]

results = []

for model, img_size, desc in tests:
    print(f"\n{model} with {desc} ({img_size}px):")
    
    test_img = create_test_image((img_size, img_size))
    
    try:
        # Test 3 times
        times = []
        for i in range(3):
            t0 = time.time()
            response = client.models.generate_content(
                model=model,
                contents=["What is 2+2?", test_img]
            )
            elapsed = time.time() - t0
            times.append(elapsed)
            print(f"  Run {i+1}: {elapsed:.2f}s")
        
        avg = sum(times) / len(times)
        results.append((model, img_size, avg))
        print(f"  ✅ Average: {avg:.2f}s")
        
    except Exception as e:
        print(f"  ❌ Error: {str(e)[:100]}")
        results.append((model, img_size, 999))

# Summary
print("\n" + "="*80)
print("SUMMARY - FASTEST TO SLOWEST:")
print("="*80)

valid_results = [(m, s, t) for m, s, t in results if t < 900]
valid_results.sort(key=lambda x: x[2])

for model, size, avg_time in valid_results:
    print(f"{model:30} | {size}px | {avg_time:.2f}s")

if valid_results:
    best = valid_results[0]
    print(f"\n🏆 FASTEST: {best[0]} with {best[1]}px image = {best[2]:.2f}s")
    
    if best[2] > 10:
        print("\n⚠️  WARNING: Even the fastest config is >10s!")
        print("   This indicates:")
        print("   1. Network latency to Gemini API servers")
        print("   2. Rate limiting on your API key")
        print("   3. Regional API performance issues")
        print("\n   Solutions:")
        print("   - Use a VPN to a different region (US/EU)")
        print("   - Deploy bot to cloud server (AWS, GCP)")
        print("   - Consider using a different AI provider (OpenAI)")
else:
    print("❌ No valid results")

print("="*80)
