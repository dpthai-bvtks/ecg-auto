# BỘ TỔNG HỢP TRI THỨC TIM MẠCH & ĐIỆN TÂM ĐỒ TOÀN CẦU
## TÍCH HỢP TỪ CÁC NGUỒN HÀNG ĐẦU QUỐC TẾ & VIỆT NAM
**Tài liệu tham khảo chuyên sâu cho Hệ thống AI Vision & Quyết định Lâm sàng (PM-ECG)**

---

### NGUỒN TƯ LIỆU THAM CHIẾU:
1. **Dr. Smith's ECG Blog:** TS.BS. Stephen W. Smith (Đại học Minnesota, Hoa Kỳ) — Tiêu chuẩn chẩn đoán OMI (Occlusion MI) & Can thiệp mạch vành.
2. **ECG Weekly / Amal Mattu:** GS.BS. Amal Mattu (Đại học Maryland, Hoa Kỳ) — Cấp cứu loạn nhịp tim & thuật toán phân biệt nhịp nhanh QRS rộng.
3. **ECG Stampede:** Trường Y Đại học Stanford — Hệ thống phân loại cấp cứu khẩn (Triage Red/Yellow/Green).
4. **PhysioNet Global Datasets:** PTB-XL (21.837 bản ghi ECG 12 chuyển đạo), Chapman-Shaoxing (45.000 ca), MIT-BIH Arrhythmia Database.
5. **Hội Tim Mạch Học Việt Nam (VNHA 2023 - 2024):** Khuyến cáo Chẩn đoán & Điều trị Hội chứng Vành cấp (Chủ tịch: PGS.TS. Phạm Mạnh Hùng).
6. **Bộ Y Tế Việt Nam:** Hướng dẫn chẩn đoán và xử trí các bệnh lý tim mạch cấp cứu & Bảng phân liều chuẩn quốc gia.

---

## MỤC LỤC
1. [Khung Phân Loại Chẩn Đoán SCP-ECG Chuẩn Quốc Tế (PTB-XL & PhysioNet)](#1-khung-phân-loại-chẩn-đoán-scp-ecg-chuẩn-quốc-tế)
2. [Bộ Tiêu Chuẩn OMI & Dấu Hiệu Tử Thần Từ Dr. Smith's ECG Blog](#2-bộ-tiêu-chuẩn-omi--dấu-hiệu-tử-thần-từ-dr-smiths-ecg-blog)
   - 2.1. Dấu hiệu Aslanger (Aslanger's sign)
   - 2.2. Dấu hiệu Cờ Nam Phi (South African Flag sign)
   - 2.3. Sóng T tối cấp (Hyperacute T-waves)
   - 2.4. Dấu hiệu Cabrera & Chapman (Nhồi máu trên nền LBBB)
3. [Thuật Toán Phân Biệt Nhịp Nhanh QRS Rộng Từ Amal Mattu & LITFL](#3-thuật-toán-phân-biệt-nhịp-nhanh-qrs-rộng)
   - 3.1. Thuật toán Vereckei aVR (2008)
   - 3.2. Tiêu chuẩn Pava chuyển đạo DII (RWPT)
   - 3.3. Thuật toán 4 bước Brugada kinh điển
4. [Hệ Thống Phân Tầng Cấp Cứu ECG Stampede (Stanford Medicine)](#4-hệ-thống-phân-tầng-cấp-cứu-ecg-stampede)
5. [Phác Đồ Xử Trí Cấp Cứu Chuẩn Bộ Y Tế Việt Nam & VNHA 2023 - 2024](#5-phác-đồ-xử-trí-cấp-cứu-chuẩn-bộ-y-tế-việt-nam--vnha)
   - 5.1. Phác đồ Hội chứng Vành Cấp & Can thiệp PCI thì đầu
   - 5.2. Bảng phân liều thuốc kháng đông & chống ngưng tập tiểu cầu (chỉnh theo eGFR và tuổi)
   - 5.3. Phác đồ Rung nhĩ cấp & Dự phòng đột quỵ
   - 5.4. Phác đồ Cơn nhịp nhanh thất & Bão điện học
   - 5.5. Cấp cứu Rối loạn điện giải đe dọa tính mạng

---

## 1. KHUNG PHÂN LOẠI CHẨN ĐOÁN SCP-ECG CHUẨN QUỐC TẾ (PTB-XL & PHYSIONET)
Bộ dữ liệu **PTB-XL** quy chuẩn hóa 71 câu chẩn đoán điện tâm đồ thành 5 nhóm bệnh học chính (Superclasses) mà AI bắt buộc phải bao quát:

1. **NORM (Normal ECG):** Bản ghi bình thường, không có rối loạn tạo nhịp, dẫn truyền hay tái cực.
2. **MI (Myocardial Infarction):** 
   - Nhồi máu thành trước (AMI), trước vách (ASMI), trước mỏm (ALMI), trước rộng (INAMI).
   - Nhồi máu thành dưới (IMI), thành dưới - bên (ILMI).
   - Nhồi máu thành sau thực thụ (PMI).
3. **STTC (ST/T Changes):**
   - Biến đổi ST-T không đặc hiệu (NST_).
   - Thiếu máu cơ tim dưới nội tâm mạc (ISCA, ISCI).
   - Tái cực sớm lành tính (BER).
4. **CD (Conduction Disturbances):**
   - Block nhánh phải (RBBB) hoàn toàn / không hoàn toàn (IRBBB).
   - Block nhánh trái (LBBB) hoàn toàn / không hoàn toàn.
   - Block phân nhánh trái trước (LAFB), Block phân nhánh trái sau (LPFB).
   - Block nhĩ thất độ I (1AVB), độ II Mobitz I/II (2AVB), độ III (3AVB / Complete AV Block).
   - Hội chứng Wolff-Parkinson-White (WPW).
5. **HYP (Hypertrophy):**
   - Dày thất trái (LVH) theo Sokolow-Lyon và Cornell.
   - Dày thất phải (RVH), Dày hai thất.
   - Dày nhĩ trái (LAE / P mitrale), Dày nhĩ phải (RAE / P pulmonale).

---

## 2. BỘ TIÊU CHUẨN OMI & DẤU HIỆU TỬ THẦN TỪ DR. SMITH'S ECG BLOG

### 2.1. Dấu hiệu Aslanger (Aslanger's sign)
- **Cơ chế:** Nhồi máu cơ tim cấp thành dưới (tắc RCA hoặc LCx) xuất hiện trên bệnh nhân **đã có sẵn bệnh nhiều thân mạch vành** (tổn thương kèm nhánh LAD). Vector thiếu máu mỏm/thành trước hướng lên trên và sang phải, triệt tiêu độ chênh lên ở DII và aVF!
- **Tiêu chuẩn nhận diện (LITFL & Dr. Smith):**
  1. **ST chênh lên đơn độc duy nhất ở DIII** (không chênh lên ở DII hay aVF).
  2. **ST chênh xuống ở $V_4 - V_6$** (chỉ điểm thiếu máu kèm theo của thành trước/bên) với sóng T dương hoặc hai pha.
  3. ST ở $V_1$ chênh cao hơn ST ở $V_2$.
- **Ý nghĩa:** Tránh bỏ sót nhồi máu thành dưới nguy cơ cao có tắc động mạch vành cấp tính. Cần chuyển can thiệp mạch vành khẩn cấp!

### 2.2. Dấu hiệu Cờ Nam Phi (South African Flag sign)
- **Cơ chế:** Tắc cấp tính **Nhánh chéo thứ nhất (First Diagonal branch - D1)** của động mạch LAD, hoặc nhánh bờ tù ($OM$) của động mạch mũ LCx.
- **Tiêu chuẩn nhận diện:**
  - ST chênh lên ở chuyển đạo **DI, aVL** (thành bên cao) VÀ chuyển đạo **$V_2$** (trước vách).
  - ST chênh xuống soi gương rõ rệt ở chuyển đạo **DIII** (thành dưới).
  - *Hình ảnh gợi nhớ:* Trên tờ giấy ghi điện tim 12 đạo trình 4 cột $\times$ 3 hàng chuẩn:
    - Cột 1 hàng 1 ($DI$), Cột 1 hàng 3 ($aVL$) $\rightarrow$ ST chênh lên.
    - Cột 2 hàng 2 ($V_2$) $\rightarrow$ ST chênh lên.
    - Cột 1 hàng 2 ($DIII$) $\rightarrow$ ST chênh xuống.
    - Bố cục 4 ô này tạo thành hình tam giác/chữ Y giống **Quốc kỳ Nam Phi**.
- **Ý nghĩa:** Chỉ điểm nhồi máu thành trước bên cao tối cấp do tắc nhánh chéo D1, vùng cơ tim bị đe dọa rất lớn.

### 2.3. Sóng T tối cấp (Hyperacute T-waves)
- Dấu hiệu xuất hiện **sớm nhất** trong vòng $5 - 30\text{ phút}$ đầu tiên của tắc cấp mạch vành, trước khi đoạn ST kịp chênh lên.
- **Đặc điểm:** Sóng T cao, đỉnh đối xứng, đáy rất rộng, biên độ sóng T tăng vọt so với phức bộ QRS đi trước ($T/QRS > 0.75$).
- Cần phân biệt với sóng T cao nhọn của Tăng Kali máu (sóng T tăng Kali có đáy hẹp hình lều chọc trời, không đối xứng rộng như OMI).

### 2.4. Dấu hiệu Cabrera & Chapman (Nhồi máu trên nền LBBB)
- **Dấu hiệu Cabrera:** Sóng $S$ có khấc sâu rộng $\ge 0.05\text{s}$ ở sườn lên tại các chuyển đạo $V_3 - V_5$ trên bệnh nhân có sẵn LBBB $\rightarrow$ Chỉ điểm sẹo nhồi máu cơ tim vách trước.
- **Dấu hiệu Chapman:** Sóng $R$ có khấc ở sườn lên tại $DI, aVL$ hoặc $V_6$ trên bệnh nhân có LBBB $\rightarrow$ Độ đặc hiệu $90\%$ chỉ điểm nhồi máu cơ tim thành trước bên.

---

## 3. THUẬT TOÁN PHÂN BIỆT NHỊP NHANH QRS RỘNG TỪ AMAL MATTU & LITFL

Khi gặp một cơn tim nhanh QRS rộng ($\ge 120\text{ms}$, tần số $> 100$ l/p), nguyên tắc vàng của GS. Amal Mattu: **"Luôn xử trí như Nhịp Nhanh Thất (VT) cho đến khi có bằng chứng ngược lại!"**

### 3.1. Thuật toán Vereckei aVR (2008)
Chỉ cần quan sát duy nhất **Chuyển đạo aVR** qua 4 bước:
1. **Bước 1:** Có sóng $R$ đơn pha khởi đầu ở $aVR$ không?
   - *Có:* **Nhịp nhanh thất (VT)**.
   - *Không:* Chuyển sang Bước 2.
2. **Bước 2:** Độ rộng của sóng $r$ hoặc $q$ khởi đầu ở $aVR > 40\text{ ms}$ (1 ô nhỏ) không?
   - *Có:* **Nhịp nhanh thất (VT)**.
   - *Không:* Chuyển sang Bước 3.
3. **Bước 3:** Sườn dốc xuống của phức bộ QRS (nếu chủ yếu âm) có khấc không?
   - *Có:* **Nhịp nhanh thất (VT)**.
   - *Không:* Chuyển sang Bước 4.
4. **Bước 4:** Tỷ lệ vận tốc kích hoạt thất $v_i / v_t \le 1$ không? (Biên độ thay đổi điện thế trong 40ms đầu so với 40ms cuối của QRS).
   - *Có:* **Nhịp nhanh thất (VT)**.
   - *Không ($v_i / v_t > 1$):* **SVT dẫn truyền lệch hướng**.

### 3.2. Tiêu chuẩn Pava Chuyển Đạo DII (R-Wave Peak Time - RWPT)
- Đo thời gian từ khởi đầu phức bộ QRS đến đỉnh cực đại của sóng R (hoặc đáy của sóng S) ở chuyển đạo $DII$:
  - Nếu $RWPT \ge 50\text{ ms}$ $\rightarrow$ Chẩn đoán **Nhịp nhanh thất (VT)** (Độ nhạy $85\%$, độ đặc hiệu $98\%$).
  - Nếu $RWPT < 50\text{ ms}$ $\rightarrow$ Nghĩ nhiều đến SVT lệch hướng.

---

## 4. HỆ THỐNG PHÂN TẦNG CẤP CỨU ECG STAMPEDE (STANFORD MEDICINE)
Hệ thống phân luồng người bệnh cấp cứu theo màu sắc giúp nhân viên y tế phản ứng tức thì:

- 🔴 **MỨC ĐỘ 1: BÁO ĐỘNG ĐỎ (TRIAGE RED - CẤP CỨU TỐI KHẨN)**
  - Nhồi máu cơ tim ST chênh lên (STEMI) hoặc tương đương STEMI (de Winter, Wellens, OMI).
  - Block nhĩ thất độ III phân ly nhĩ thất hoặc Mobitz II có tụt huyết áp.
  - Nhịp nhanh thất (VT), Rung thất (VF), Rung nhĩ đáp ứng thất cực nhanh có sốc tim.
  - Tăng Kali máu nặng dạng sóng hình sin đe dọa ngừng tim.
  - *Hành động:* Kích hoạt Cathlab / Máy sốc điện / Máy tạo nhịp trong vòng $< 10\text{ phút}$.

- 🟡 **MỨC ĐỘ 2: BÁO ĐỘNG VÀNG (TRIAGE YELLOW - CẦN CAN THIỆP SỚM < 1 GIỜ)**
  - Hội chứng vành cấp không ST chênh lên (NSTE-ACS) nguy cơ cao.
  - QTc kéo dài $> 500\text{ ms}$ (nguy cơ xoắn đỉnh).
  - Hội chứng Brugada Type 1 có triệu chứng ngất.
  - Thuyên tắc phổi cấp có tăng gánh thất phải (S1Q3T3, RBBB mới).
  - *Hành động:* Đặt monitor theo dõi liên tục, lập đường truyền, xét nghiệm men tim và điện giải đồ khẩn.

- 🟢 **MỨC ĐỘ 3: MỨC ĐỘ XANH (TRIAGE GREEN - THEO DÕI THƯỜNG QUY)**
  - Điện tâm đồ bình thường (Normal ECG).
  - Tái cực sớm lành tính (BER), Nhịp nhanh xoang / chậm xoang sinh lý.
  - Block nhánh cũ không triệu chứng.
  - *Hành động:* Khám chuyên khoa, tư vấn lối sống và tái khám định kỳ.

---

## 5. PHÁC ĐỒ XỬ TRÍ CẤP CỨU CHUẨN BỘ Y TẾ VIỆT NAM & VNHA 2023 - 2024

### 5.1. Phác đồ Hội chứng Vành Cấp & Can Thiệp Tái Tưới Máu Thì Đầu (PCI)
- **Kháng kết tập tiểu cầu kép (DAPT) - Cho ngay tại phòng cấp cứu:**
  - **Aspirin:** Liều nạp $150 - 300\text{ mg}$ nhai nuốt (Aspirin pH8 nên nhai nát để hấp thu nhanh sau 15–30 phút), liều duy trì $75 - 100\text{ mg/ngày}$.
  - **Thuốc ức chế $P2Y_{12}$:**
    * *Lựa chọn ưu tiên 1:* **Ticagrelor** $180\text{ mg}$ (2 viên 90mg) liều nạp, duy trì $90\text{ mg} \times 2\text{ lần/ngày}$.
    * *Lựa chọn ưu tiên 2 (nếu không có Ticagrelor hoặc bệnh nhân $>75$ tuổi có nguy cơ xuất huyết cao):* **Clopidogrel (Plavix)** $300 - 600\text{ mg}$ liều nạp, duy trì $75\text{ mg/ngày}$.
- **Thuốc Kháng đông đường tiêm:**
  - **Enoxaparin (Lovenox):**
    * *Tuổi $< 75$ và chức năng thận bình thường:* Bolus tĩnh mạch $30\text{ mg}$ ngay lập tức, sau 15 phút tiêm dưới da $1\text{ mg/kg}$ mỗi 12 giờ.
    * *Tuổi $\ge 75$:* Không dùng liều bolus tĩnh mạch, tiêm dưới da $0.75\text{ mg/kg}$ mỗi 12 giờ.
    * *Suy thận nặng ($eGFR < 30\text{ ml/phút}$):* Tiêm dưới da $1\text{ mg/kg}$ mỗi 24 giờ.
  - **Heparin không phân đoạn (UFH):** Bolus TM $60 - 70\text{ UI/kg}$ (tối đa $4000\text{ UI}$), truyền duy trì $12 - 15\text{ UI/kg/h}$ chỉnh liều theo aPTT mục tiêu gấp $1.5 - 2.5$ lần chứng.
- **Statin cường độ cao:** **Atorvastatin $80\text{ mg}$** hoặc Rosuvastatin $40\text{ mg}$ uống ngay 1 liều càng sớm càng tốt trước can thiệp.

### 5.2. Phác đồ Thuốc Tiêu Sợi Huyết (Khi không thể chuyển đến trung tâm PCI < 120 phút)
- Thời gian vàng: Tốt nhất trong vòng **$< 3\text{ giờ}$** đầu (tối đa 12 giờ) kể từ khi khởi phát đau ngực.
- **Alteplase (rt-PA - Actilyse 50mg):** Phác đồ gia tốc 90 phút:
  - Bolus TM $15\text{ mg}$ trong $1 - 2\text{ phút}$.
  - Truyền TM $0.75\text{ mg/kg}$ trong $30\text{ phút}$ (tối đa $50\text{ mg}$).
  - Truyền TM $0.5\text{ mg/kg}$ trong $60\text{ phút}$ tiếp theo (tối đa $35\text{ mg}$). Tổng liều tối đa không quá $100\text{ mg}$.
- **Tenecteplase (TNK-tPA):** Tiêm tĩnh mạch 1 lần duy nhất theo cân nặng:
  - $< 60\text{ kg}$: $30\text{ mg}$ (6.000 UI)
  - $60 - 70\text{ kg}$: $35\text{ mg}$ (7.000 UI)
  - $70 - 80\text{ kg}$: $40\text{ mg}$ (8.000 UI)
  - $80 - 90\text{ kg}$: $45\text{ mg}$ (9.000 UI)
  - $\ge 90\text{ kg}$: $50\text{ mg}$ (10.000 UI)

### 5.3. Phác đồ Cơn Nhịp Nhanh Thất & Bão Điện Học (Electrical Storm)
- **Huyết động không ổn định (tụt HA, mất mạch, vô thức):**
  - Đánh sốc điện đồng bộ khẩn cấp $100 - 200\text{ J}$ (Biphasic).
  - Nếu thành Rung thất / Vô mạch: Sốc điện khử rung không đồng bộ $200\text{ J}$ + CPR ngay.
- **Huyết động còn ổn định:**
  - **Amiodarone (Cordarone 150mg/3ml):** Pha $150\text{ mg}$ trong $100\text{ ml}$ Glucose $5\%$ truyền TM trong $10\text{ phút}$. Sau đó truyền duy trì $1\text{ mg/phút}$ trong 6 giờ, tiếp theo $0.5\text{ mg/phút}$ trong 18 giờ tiếp theo (tổng liều tối đa $2.2\text{ g/24h}$).
  - **Lidocaine:** $1 - 1.5\text{ mg/kg}$ tiêm TM chậm nếu nghi ngờ thiếu máu cục bộ cơ tim cấp.

### 5.4. Bảng Tra cứu Liều Vận Mạch trong Sốc Tim (Cardiogenic Shock)
| Thuốc | Liều Khởi đầu | Liều Tối đa | Cơ chế / Chỉ định Ưu tiên |
|---|---|---|---|
| **Noradrenaline (Norepinephrine)** | $0.05 - 0.1\text{ mcg/kg/phút}$ | $1.0 - 2.0\text{ mcg/kg/phút}$ | **Lựa chọn hàng đầu trong sốc tim:** Co mạch nâng huyết áp mà ít làm tăng nhịp tim |
| **Dobutamine** | $2.5 - 5.0\text{ mcg/kg/phút}$ | $20\text{ mcg/kg/phút}$ | Tăng sức bóp cơ tim (Inotrope), dùng khi huyết áp tâm thu đã đạt $\ge 85 - 90\text{ mmHg}$ |
| **Adrenaline (Epinephrine)** | $0.05 - 0.5\text{ mcg/kg/phút}$ | $1.0\text{ mcg/kg/phút}$ | Dùng khi sốc trơ với Noradrenaline hoặc trong cấp cứu ngừng tuần hoàn |
