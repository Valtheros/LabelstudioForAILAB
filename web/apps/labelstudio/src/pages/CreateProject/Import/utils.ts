import { API } from "apps/labelstudio/src/providers/ApiProvider";

export const importFiles = async ({
  body,
  project,
  onFinish,
  onError,
}: {
  body: FormData;
  project: APIProject;
  onFinish?: (response: any) => void;
  onError?: (response: any) => void;
}) => {
  const res = await API.invoke(
    "importFiles",
    { pk: project.id },
    { headers: { "Content-Type": "multipart/form-data" }, body },
  );

  if (res && !res.error) {
    await onFinish?.(res);
  } else {
    onError?.(res?.response);
  }
};
