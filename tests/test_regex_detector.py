from delere.core.models import Detection, DetectorSource, PIICategory, PageText
from delere.detectors.regex import RegexDetector
from delere.profiles.loader import load_profile


def _make_page(text: str, page_number: int = 0) -> PageText:
    """Build a PageText with simple word positions for testing.

    Each word gets a synthetic bounding box at a fixed vertical position
    with horizontal offsets based on character position in the text.
    """
    words = []
    x = 72.0
    for block_no, line in enumerate(text.split("\n")):
        for word_no, word in enumerate(line.split()):
            width = len(word) * 7.0
            words.append((x, 100.0, x + width, 112.0, word, block_no, 0, word_no))
            x += width + 7.0
        x = 72.0

    return PageText(page_number=page_number, full_text=text, words=words)


class TestPIPEDADetection:
    def test_sin_detected_with_keyword(self):
        page = _make_page("My SIN is 123-456-789 and I live in Toronto.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        sins = [d for d in results if d.category == PIICategory.SIN]
        assert len(sins) == 1
        assert sins[0].text == "123-456-789"
        assert sins[0].source == DetectorSource.REGEX

    def test_sin_without_keyword_not_detected(self):
        page = _make_page("The order number is 123-456-789 for your reference.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        sins = [d for d in results if d.category == PIICategory.SIN]
        assert len(sins) == 0

    def test_email_detected(self):
        page = _make_page("Contact sarah@example.com for details.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        emails = [d for d in results if d.category == PIICategory.EMAIL]
        assert len(emails) == 1
        assert emails[0].text == "sarah@example.com"

    def test_phone_detected(self):
        page = _make_page("Call us at (416) 555-0123 anytime.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        phones = [d for d in results if d.category == PIICategory.PHONE]
        assert len(phones) >= 1

    def test_postal_code_detected(self):
        page = _make_page("Mailing address: Toronto, ON M5V 2T6")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        addresses = [d for d in results if d.category == PIICategory.ADDRESS]
        assert any("M5V" in d.text for d in addresses)

    def test_credit_card_detected(self):
        page = _make_page("Card number: 4111-1111-1111-1111 on file.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        cards = [d for d in results if d.category == PIICategory.CREDIT_CARD]
        assert len(cards) >= 1

    def test_ipv4_detected(self):
        page = _make_page("Server at 192.168.1.100 responded.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        ips = [d for d in results if d.category == PIICategory.IP_ADDRESS]
        assert len(ips) == 1
        assert ips[0].text == "192.168.1.100"


class TestHIPAADetection:
    def test_ssn_formatted_detected(self):
        page = _make_page("Patient SSN: 123-45-6789")
        detector = RegexDetector(load_profile("hipaa"))
        results = detector.detect([page], page.full_text)

        ssns = [d for d in results if d.category == PIICategory.SSN]
        assert len(ssns) == 1
        assert ssns[0].text == "123-45-6789"

    def test_ssn_invalid_prefix_not_detected(self):
        """SSNs starting with 000, 666, or 9xx are invalid per IRS rules."""
        page = _make_page("Number: 000-12-3456")
        detector = RegexDetector(load_profile("hipaa"))
        results = detector.detect([page], page.full_text)

        ssns = [d for d in results if d.category == PIICategory.SSN]
        assert len(ssns) == 0

    def test_medical_record_number_detected(self):
        page = _make_page("MRN: 12345678 for patient admission.")
        detector = RegexDetector(load_profile("hipaa"))
        results = detector.detect([page], page.full_text)

        mrns = [d for d in results if d.category == PIICategory.MEDICAL_RECORD_NUMBER]
        assert len(mrns) >= 1


class TestGDPRDetection:
    def test_italian_codice_fiscale_detected(self):
        page = _make_page("Codice Fiscale: RSSMRA85M01H501Z is on file.")
        detector = RegexDetector(load_profile("gdpr"))
        results = detector.detect([page], page.full_text)

        ids = [d for d in results if d.category == PIICategory.NATIONAL_ID]
        assert any("RSSMRA85M01H501Z" in d.text for d in ids)

    def test_spanish_dni_detected(self):
        page = _make_page("DNI: 12345678Z provided.")
        detector = RegexDetector(load_profile("gdpr"))
        results = detector.detect([page], page.full_text)

        ids = [d for d in results if d.category == PIICategory.NATIONAL_ID]
        assert any("12345678Z" in d.text for d in ids)


class TestStreetAddressDetection:
    def test_numbered_street_detected(self):
        page = _make_page("Residence: 5713 DEVINE PL REGINA SK")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        addresses = [d for d in results if d.category == PIICategory.ADDRESS]
        assert any("5713 DEVINE PL" in d.text for d in addresses)

    def test_street_name_with_keyword_proximity(self):
        page = _make_page("Current address FIREFLY RD unit 2")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        addresses = [d for d in results if d.category == PIICategory.ADDRESS]
        assert any("FIREFLY RD" in d.text for d in addresses)

    def test_street_name_without_keyword_not_detected(self):
        """Street name without nearby address keyword should be skipped."""
        page = _make_page("The FIREFLY RD was paved last year after negotiations.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        addresses = [d for d in results if d.category == PIICategory.ADDRESS
                     and "FIREFLY RD" in d.text]
        assert len(addresses) == 0


class TestDatePatterns:
    def test_ddmonyyyy_detected(self):
        page = _make_page("DOB: 08Sep1989 on the application form.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        dates = [d for d in results if d.category == PIICategory.DATE_OF_BIRTH]
        assert any("08Sep1989" in d.text for d in dates)

    def test_mon_dd_yyyy_detected(self):
        page = _make_page("Born January 15, 2001 in Ottawa.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        dates = [d for d in results if d.category == PIICategory.DATE_OF_BIRTH]
        assert any("January 15, 2001" in d.text for d in dates)

    def test_form_field_name_detected(self):
        page = _make_page("Surname: PATEL Given Name(s): HASHITA")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        names = [d for d in results if d.category == PIICategory.NAME]
        texts = [d.text for d in names]
        assert any("PATEL" in t for t in texts)
        assert any("HASHITA" in t for t in texts)


class TestEdgeCases:
    def test_empty_text(self):
        page = _make_page("")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)
        assert results == []

    def test_no_pii_in_text(self):
        page = _make_page("The quick brown fox jumps over the lazy dog.")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        # Should only find non-keyword-gated patterns if they match
        # No emails, no SINs, no phone numbers in this text
        assert all(d.category not in (PIICategory.SIN, PIICategory.EMAIL) for d in results)

    def test_confidence_is_from_pattern(self):
        page = _make_page("Email: test@example.com")
        detector = RegexDetector(load_profile("pipeda"))
        results = detector.detect([page], page.full_text)

        emails = [d for d in results if d.category == PIICategory.EMAIL]
        assert len(emails) == 1
        assert emails[0].confidence == 0.95
