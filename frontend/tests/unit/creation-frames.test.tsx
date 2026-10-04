import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CreationFrames } from '@/components/creation/creation-frames';
import { creationMaterial } from '../helpers/creation-fixtures';
import { render } from '../helpers/query-render';

const preview =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=';
const previewBytes = Uint8Array.from(atob(preview), (character) =>
  character.charCodeAt(0),
);
const frame = {
  id: 'frame-one',
  material_id: 'material-1',
  material_revision_sha256: creationMaterial.current_revision.sha256,
  timestamp_ms: 1234,
  frame_sha256: 'f'.repeat(64),
  preview_sha256: bytesToHex(sha256(previewBytes)),
  preview_width: 1,
  preview_height: 1,
  preview_media_type: 'image/png',
  preview_data_base64: preview,
};

describe('actual creation frame evidence', () => {
  it('shows a bounded verified PNG and links a matching source, timestamp and hash', () => {
    render(
      <CreationFrames
        materials={[creationMaterial]}
        data={{
          frames: [frame],
          media_evidence: [
            {
              frame_id: frame.id,
              material_id: frame.material_id,
              sha256: frame.material_revision_sha256,
              timestamp_ms: frame.timestamp_ms,
              status: 'inference',
              claim: '角色动机仍待核查。',
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole('img')).toHaveAttribute(
      'src',
      `data:image/png;base64,${preview}`,
    );
    expect(screen.getByRole('img')).toHaveAccessibleName(
      '原创材料 00:00:01.234 的实际抽样帧',
    );
    expect(
      screen.getByRole('link', { name: /回看对应抽样帧/ }),
    ).toHaveAttribute('href', '#creation-frame-frame-one');
    expect(screen.getByText('推断候选 · 需人工核查')).toBeInTheDocument();
  });

  it.each([
    { preview_media_type: 'image/svg+xml' },
    { preview_data_base64: 'https://untrusted.example/frame.png' },
    { preview_sha256: '0'.repeat(64) },
    { preview_width: 300_000 },
  ])('does not render unverified or arbitrary media %j', (override) => {
    render(
      <CreationFrames
        materials={[creationMaterial]}
        data={{ frames: [{ ...frame, ...override }] }}
      />,
    );
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('已停止展示');
  });

  it('does not substitute another timestamp as the evidence of a claim', () => {
    render(
      <CreationFrames
        materials={[creationMaterial]}
        data={{
          frames: [frame],
          media_evidence: [
            {
              frame_id: frame.id,
              material_id: frame.material_id,
              sha256: frame.material_revision_sha256,
              timestamp_ms: frame.timestamp_ms + 1,
              status: 'observation',
              claim: '需要回看。',
            },
          ],
        }}
      />,
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText(/不能用其他画面替代依据/)).toBeInTheDocument();
  });
});
