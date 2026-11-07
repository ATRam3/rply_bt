# 🔥 TESSERACT OCR INSTALLATION GUIDE

## **For Windows:**

### **Method 1: Using Installer (Recommended)**

1. **Download Tesseract installer:**
   - Go to: https://github.com/UB-Mannheim/tesseract/wiki
   - Download: `tesseract-ocr-w64-setup-5.3.3.20231005.exe` (or latest version)

2. **Install:**
   - Run the downloaded `.exe` file
   - **IMPORTANT:** During installation, note the installation path (usually `C:\Program Files\Tesseract-OCR`)
   - Check "Add to PATH" if available

3. **Verify Installation:**
   ```bash
   tesseract --version
   ```

   If this works, you're done! If not, continue to step 4.

4. **Add to PATH manually:**
   - Open Windows Settings → System → About → Advanced system settings
   - Click "Environment Variables"
   - Under "System variables", find "Path"
   - Click "Edit" → "New"
   - Add: `C:\Program Files\Tesseract-OCR`
   - Click OK, OK, OK
   - Restart your terminal

### **Method 2: Using Chocolatey (If you have it)**

```bash
choco install tesseract
```

### **Method 3: Using Scoop (If you have it)**

```bash
scoop install tesseract
```

---

## **Verify Installation:**

Run this in your terminal:

```bash
tesseract --version
```

You should see:
```
tesseract 5.3.3
 leptonica-1.83.1
```

---

## **Test OCR:**

Create a test image with text and run:

```bash
tesseract test_image.png output
```

If it creates `output.txt` with text, you're ready!

---

## **If Tesseract is Not Found:**

The bot will automatically set the path if installed in the default location.

If installed elsewhere, edit bot.py and add this line at the top:

```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Path\To\tesseract.exe'
```

---

**After installation, run the bot and it will use OCR instead of Gemini!** 🚀
