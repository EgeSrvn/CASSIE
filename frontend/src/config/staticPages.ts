import aboutPage from '../../../config/about_page.json'
import faqPage from '../../../config/faq_page.json'

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

export const STATIC_PAGES: Record<string, StaticPageConfig> = {
  about: {
    type: 'content',
    content: aboutPage,
  },
  faq: {
    type: 'faq',
    content: faqPage,
  },
}
