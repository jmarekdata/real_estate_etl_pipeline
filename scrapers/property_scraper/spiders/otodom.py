import scrapy

class OtodomSpider(scrapy.Spider):
    name = 'otodom'
    
    start_urls = ['https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/lodzkie/lodz/lodz/lodz']

    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'ROBOTSTXT_OBEY': False, 
        'CONCURRENT_REQUESTS': 1, 
        'DOWNLOAD_DELAY': 3 
    }

    def parse(self, response):
        if response.status == 200:
            print("\n" + "="*50)
            print("True.")
            print(f"Tytuł strony: {response.xpath('//title/text()').get()}")
            print("="*50 + "\n")
        else:
            print(f"\nFalse. Status: {response.status}\n")