# Telemedi B2C — publiczna wersja dashboardu

Interaktywny dashboard do zadania rekrutacyjnego Head of B2C, zbudowany na **fikcyjnych danych** z okresu 2024-10-01 do 2026-09-30.

## Uruchomienie

`pip install -r requirements.txt` i `streamlit run app/streamlit_app.py`.

## Definicje i zastrzeżenia

- Retencja D90 to powtórny zakup do 90 dni od pierwszego zakupu, wyłącznie dla dojrzałych kohort.
- Kontrybucja przed marketingiem = przychód netto konsultacji minus koszty lekarzy plus przychody GO.
- Wynik po marketingu = kontrybucja minus spend i koszt afiliacji według modelu last non-direct. **Nie jest to EBITDA.**
- TEST-QA wyłączono z KPI komercyjnych i pokazano jako anomalię wymagającą wyjaśnienia.
- Atrybucja last non-direct nie dowodzi inkrementalności ani przyczynowości.
- Kohorty i koszty marketingowe mają odrębne reguły atrybucji. Należy czytać opisy poszczególnych wykresów.

## Bezpieczeństwo

Repozytorium zawiera tylko aplikację i dane agregatowe w `app/data/`; **nie należy dodawać** oryginalnych tabel, `patient.parquet`, danych sesji, wizyt, zamówień ani pliku bazy DuckDB. Dane są fikcyjne. Mechanizm sprawdza nazwy kolumn, ale nie jest formalną anonimizacją danych medycznych.
