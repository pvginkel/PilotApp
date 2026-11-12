/**
 * A confirmation (F22): Pilot's ask for the go on one act. Its item is a compact yellow card, drawn
 * as an action is: the head with the auto pilot mark while the switch would answer it (F4.4) and
 * its reason line, whose tooltip says the ground (F22.1); the title; the proposal as its text, full
 * width; and its block under it, Yes and No in an action's row of buttons (F22.2;
 * confirm-answer.tsx), which is the block's controls inside a document too (F22.7); the prose
 * folded under Details, which Less folds again (F22.4). Gone to at its address, its block flashes
 * (F97). A registered one whose writer Pilot asked about its block carries the block's mark in its
 * head (F52.2; writer-asked.tsx). Its attachments follow (F17.5), and Pilot's dots end the card
 * while Pilot writes it (F35). In an archived project Yes and No stand disabled, which the API
 * refuses until Bring back (D012).
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { LinkedText } from '@/components/shared/linked-text';
import { Markdown } from '@/components/shared/markdown';
import { Attachments } from '@/components/timeline/attachments';
import { Block } from '@/components/timeline/block';
import { Proposal } from '@/components/timeline/confirm-answer';
import { ItemHead } from '@/components/timeline/item-head';
import { autopilotMayTake } from '@/components/timeline/may-take';
import { PilotWriting } from '@/components/timeline/writing';
import { useShownProject } from '@/hooks/use-project-address';
import { useAutopilotOff } from '@/hooks/use-projects';
import { blocksOf, isProse, titleOf, type TimelineItem } from '@/hooks/use-timeline';

/** An open confirmation item's card. */
export function Confirmation({ item }: { item: TimelineItem }) {
  const { id: projectId } = useShownProject();
  const [block] = blocksOf(item);
  const autopilotOff = useAutopilotOff(projectId);
  const [details, setDetails] = useState(false);
  // The API gives every prose item but the opening its text.
  const prose = item.body!.filter(isProse);
  return (
    <div className="item-body">
      <ItemHead item={item} because={block.because} mayTake={autopilotMayTake(item, block, autopilotOff)} asked={block.writer_asked} />
      <div className="item-title" data-testid="timeline.item.title">
        <LinkedText text={titleOf(item)} />
      </div>
      <Proposal block={block} />
      <Block item={item} block={block} solo />
      {prose.length > 0 && (
        <div className="confirm-foot">
          <button
            type="button"
            className="link details"
            onClick={() => setDetails(!details)}
            aria-expanded={details}
            data-testid="timeline.confirm.details"
          >
            {details ? <ChevronUp className="icon" aria-hidden="true" /> : <ChevronDown className="icon" aria-hidden="true" />}
            {details ? 'Less' : 'Details'}
          </button>
        </div>
      )}
      {details && (
        <div className="confirm-prose" data-testid="timeline.confirm.prose">
          {prose.map((part, index) => (
            <Markdown key={index} text={part.markdown} />
          ))}
        </div>
      )}
      <Attachments item={item} />
      {item.writing && <PilotWriting />}
    </div>
  );
}
