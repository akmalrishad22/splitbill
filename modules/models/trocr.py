import torch
import re
import easyocr
import numpy as np
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from modules.data.receipt_data import ItemData, ReceiptData

class TrOCRModel:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading TrOCR to {self.device}...")
        
        self.processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
        self.model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed").to(self.device)
        
        self.detector = easyocr.Reader(['en'], gpu=(self.device == 'cuda'))

    def run(self, image_input):
        if not isinstance(image_input, Image.Image):
            img = Image.open(image_input).convert("RGB")
        else:
            img = image_input.convert("RGB")
        
        line_crops = self._preprocess(img)
        raw_lines = self._inference(line_crops)
        print("rawline",raw_lines)        
        result = self._formatting(raw_lines)
        print("result",result)

        return result

    def _preprocess(self, img_pil):
        img_array = np.array(img_pil)
        
        detections = self.detector.readtext(img_array)
        
        line_crops = []
        for (bbox, text, prob) in detections:
            top_left = bbox[0]
            bottom_right = bbox[2]
            
            crop = img_pil.crop((
                int(top_left[0]), 
                int(top_left[1]), 
                int(bottom_right[0]), 
                int(bottom_right[1])
            ))
            line_crops.append(crop)
            
        return line_crops

    def _inference(self, line_crops):
        texts = []
        for crop in line_crops:
            pixel_values = self.processor(images=crop, return_tensors="pt").pixel_values.to(self.device)
            
            generated_ids = self.model.generate(pixel_values)
            text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            texts.append(text)
        return texts

    def _formatting(self, raw_lines: list) -> ReceiptData:
        items = {}
        grand_total = 0.0
        
        clean_lines = [line.strip() for line in raw_lines if line.strip()]
        
        i = 0
        item_id_counter = 1
        while i < len(clean_lines):
            current_line = clean_lines[i]
            
            if any(key in current_line.upper() for key in ["TOTAL", "SUB TOTAL", "CASH", "CHANGE"]):
                if i + 1 < len(clean_lines):
                    potential_price = clean_lines[i+1]
                    price_val = self._extract_price(potential_price)
                    
                    if "SUB TOTAL" in current_line.upper() or "TOTAL SALES" in current_line.upper():
                        grand_total = price_val
                    
                    i += 2 
                    continue
            
            if i + 1 < len(clean_lines):
                next_line = clean_lines[i+1]
                price_val = self._extract_price(next_line)
                
                if price_val > 0:
                    new_item = ItemData(
                        name=current_line,
                        count=1,
                        total_price=price_val,
                        id=item_id_counter
                    )
                    items[item_id_counter] = new_item
                    item_id_counter += 1
                    i += 2
                    continue
            
            i += 1
            
        return ReceiptData(items=items, total=grand_total)

    def _extract_price(self, text):
        """Helper untuk membersihkan string harga menjadi float."""
        clean_str = re.sub(r'[^\d]', '', text)
        try:
            return float(clean_str) if clean_str else 0.0
        except ValueError:
            return 0.0