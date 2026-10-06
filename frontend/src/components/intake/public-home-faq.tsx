import Link from 'next/link';
import { publicQuestions } from '@/components/intake/public-home-content';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import { ItemTitle } from '@/components/ui/item';

export function PublicHomeFaq() {
  return (
    <section
      aria-labelledby="questions-title"
      className="flex flex-col gap-4 scroll-mt-24"
      id="questions"
    >
      <ItemTitle>
        <h2 id="questions-title">常见问题</h2>
      </ItemTitle>
      <Accordion
        type="multiple"
        defaultValue={publicQuestions.map((item) => item.id)}
      >
        {publicQuestions.map(({ id, question, answer }) => (
          <AccordionItem id={id} key={id} value={id}>
            <AccordionTrigger>{question}</AccordionTrigger>
            <AccordionContent>{answer}</AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
      <Button asChild className="self-start" variant="ghost">
        <Link href="/guide/">阅读视频分析与自托管使用指南</Link>
      </Button>
    </section>
  );
}
