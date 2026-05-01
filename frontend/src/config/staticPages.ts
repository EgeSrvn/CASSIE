import aboutPage from '../../../config/about_page.json'
import faqPage from '../../../config/faq_page.json'
import agreementText from '../../../agreement.txt?raw'
import kvkkText from '../../../kvkk.txt?raw'

export interface StaticPageContent {
  title: string
  description: string
  sections: Array<{
    heading: string
    body: string[]
  }>
}

export interface FaqPageContent {
  title: string
  description: string
  items: Array<{
    question: string
    answer: string[]
  }>
}

export type StaticPageConfig =
  | { type: 'content'; content: StaticPageContent }
  | { type: 'faq'; content: FaqPageContent }
  | { type: 'document'; content: StaticPageContent & { document: string } }

export const STATIC_PAGES: Record<string, StaticPageConfig> = {
  about: {
    type: 'content',
    content: aboutPage,
  },
  faq: {
    type: 'faq',
    content: faqPage,
  },
  terms: {
    type: 'document',
    content: {
      title: 'Terms of Service',
      description: 'User agreement for accessing and using CASSIE.',
      sections: [],
      document: agreementText,
    },
  },
  kvkk: {
    type: 'document',
    content: {
      title: 'KVKK Aydinlatma Metni',
      description: 'Kisisel verilerin islenmesine iliskin CASSIE bilgilendirme metni.',
      sections: [],
      document: kvkkText,
    },
  },
}
